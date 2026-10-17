"""Explicitly enabled, one-request-per-account CPA pool. No provider fallback."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

import psutil
import yaml
from locking import file_lock

# Identity string sent with upstream quota/generate calls; override if the provider changes it.
UPSTREAM_UA = os.environ.get('ORCHESTRATOR_UPSTREAM_UA', 'antigravity/2.15.1 windows/amd64')


def parse_quota(data):
    buckets = []
    for group in data.get('groups',[]):
        if not str(group.get('displayName','')).startswith('Gemini'):
            continue
        for bucket in group.get('buckets',[]):
            fraction = bucket.get('remainingFraction')
            if fraction is None or isinstance(fraction,bool):
                continue
            try:
                fraction = float(fraction)
                if not math.isfinite(fraction) or not 0<=fraction<=1:
                    continue
            except (ValueError,TypeError):
                continue
            try:
                reset = datetime.datetime.fromisoformat(bucket['resetTime'].replace('Z','+00:00')).timestamp()
            except (KeyError,TypeError,ValueError):
                reset = None
            buckets.append({'group':str(group['displayName'])[:80],'fraction':fraction,'reset_at':reset,
                            'bucket_id':str(bucket.get('bucketId',''))[:80],
                            'window':str(bucket.get('window',''))[:20],
                            'label':str(bucket.get('displayName',''))[:80]})
    if not buckets:
        raise ValueError('Quota response has no valid Gemini buckets')
    limiting = min(buckets,key=lambda b:b['fraction'])
    return limiting['fraction'],limiting['reset_at'],buckets


class ProviderError(RuntimeError):
    def __init__(self, kind, retryable=False, cooldown=0, usage=None):
        super().__init__(kind)
        self.kind, self.retryable, self.cooldown = kind, retryable, cooldown
        self.usage=usage


class NoCapacity(ProviderError):
    """No request was sent: keep the task pending instead of spending a retry."""


class Pool:
    def __init__(self, store, root=None):
        self.store = store
        self.root = Path(root or os.environ.get('ORCHESTRATOR_POOL_ROOT', str(Path.home()/'.orchestrator/cpa-pool'))).resolve()
        self.binary = Path(os.environ.get('ORCHESTRATOR_CPA_BINARY', shutil.which('cli-proxy-api') or 'cli-proxy-api'))
        self.model = 'gemini-3.8-flash-high'
        self.guard = threading.Lock()
        self.cursor = 0
        self._identities = {}
        self._epoch = {}
        self._identity_lock = threading.Lock()

    def enabled(self):
        return os.environ.get('ORCHESTRATOR_GEMINI_ENABLED') == '1'

    def _config(self, number):
        folder = self.root / f'h{number:02}'
        cfg = yaml.safe_load((folder / 'config.yaml').read_text(encoding='utf-8'))
        if cfg.get('host') != '127.0.0.1' or cfg.get('port') != 8400+number:
            raise ValueError('CPA must listen on its assigned loopback port')
        auth = Path(cfg['auth-dir']).resolve()
        if auth != (folder/'auth').resolve() or len(list(auth.glob('*.json'))) != 1:
            raise ValueError('Each CPA must have exactly one account')
        q = cfg.get('quota-exceeded', {})
        if q.get('switch-project') or q.get('switch-preview-model'):
            raise ValueError('CPA account/model fallback must be disabled')
        return cfg

    @staticmethod
    def online(port):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.15):
                return True
        except OSError:
            return False

    @staticmethod
    def alive(info):
        try:
            process = psutil.Process(info['pid'])
            return abs(process.create_time()-info['pid_bas']) < .1 and process.is_running()
        except (psutil.Error, KeyError, TypeError):
            return False

    def _reap(self, lock):
        try:
            raw = lock.read_text(encoding='utf-8')
            info = json.loads(raw)
            # A live owner is never evicted, even after TTL, avoiding overlapping requests.
            if self.alive(info):
                return
            if 'pid_bas' not in info:
                if psutil.pid_exists(info.get('pid',0)) or info.get('bitis', time.time()+10)>time.time():
                    return
            if lock.read_text(encoding='utf-8') == raw:
                lock.unlink(missing_ok=True)
        except (ValueError, OSError):
            # Leave partial/new and unknown leases alone.
            pass

    def status(self):
        health = self.store.accounts()
        quotas = self.store.quotas()
        dispatches = self.store.dispatches()
        generations = self.store.generations()
        out = []
        for n in range(1,16):
            aid = f'h{n:02}'
            valid = True
            try:
                self._config(n)
            except (OSError, ValueError, KeyError, yaml.YAMLError):
                valid = False
            lock = self.root/'kira'/f'{8400+n}.kira'
            out.append({'account_id':aid, 'configured':valid, 'online':self.online(8400+n),
                        'leased':lock.exists(), 'cooldown_seconds':max(0, int(health.get(aid,{}).get('cooldown_until',0)-time.time())),
                        'quota':quotas.get(aid), 'quota_fresh':time.time()-quotas.get(aid,{}).get('checked_at',0)<120})
            out[-1]['dispatch']=dispatches.get(aid,{'leases':0,'last_selected':None})
            out[-1]['generation']=generations.get(aid,{'requests':0,'completed':0,'failed':0,'known_tokens':0,'unknown_usage':0})
        return {'enabled':self.enabled(), 'model':self.model, 'accounts':out}

    @contextmanager
    def acquire(self, preferred=None):
        if not self.enabled():
            raise ProviderError('Gemini MCP execution disabled')
        lease_dir = self.root/'kira'
        lease_dir.mkdir(parents=True,exist_ok=True)
        health = self.store.accounts()
        quotas = self.store.quotas()
        dispatches = self.store.dispatches()
        chosen = None
        with self.guard:
            order = list(range(self.cursor+1,16)) + list(range(1,self.cursor+1))
            order.sort(key=lambda n:(dispatches.get(f'h{n:02}',{}).get('leases',0),
                                     dispatches.get(f'h{n:02}',{}).get('last_selected',0)))
            if preferred:
                if preferred not in {f'h{n:02}' for n in range(1,16)}:
                    raise ValueError('Unknown account_id')
                order = [int(preferred[1:])]
            for n in order:
                aid = f'h{n:02}'
                if health.get(aid,{}).get('cooldown_until',0) > time.time():
                    continue
                quota = quotas.get(aid,{})
                if quota.get('fraction') is None or time.time()-quota.get('checked_at',0)>120 or quota['fraction']<.02:
                    continue
                self._config(n)
                lock = lease_dir/f'{8400+n}.kira'
                token = uuid.uuid4().hex
                try:
                    with file_lock(lock.with_suffix('.guard')):
                        if lock.exists():
                            self._reap(lock)
                        fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                        with os.fdopen(fd,'w',encoding='utf-8') as f:
                            json.dump({'bitis':time.time()+600,'pid':os.getpid(),
                                       'pid_bas':psutil.Process().create_time(),'token':token},f)
                except (FileExistsError,BlockingIOError):
                    continue
                chosen = (aid,n,lock,token)
                try:
                    self.store.dispatch(aid)
                except Exception:
                    if json.loads(lock.read_text(encoding='utf-8')).get('token')==token:
                        lock.unlink()
                    raise
                self.cursor = n % 15
                break
        if not chosen:
            raise NoCapacity('No fresh eligible account: leased, quota low/unknown, or cooling down')
        aid,n,lock,token = chosen
        try:
            yield aid, f'http://127.0.0.1:{8400+n}'
        finally:
            try:
                if json.loads(lock.read_text(encoding='utf-8')).get('token') == token:
                    lock.unlink()
            except (OSError,ValueError):
                pass

    def _boot(self, n):
        if self.online(8400+n):
            return
        if not self.binary.is_file():
            raise ProviderError('CPA binary missing')
        folder = self.root/f'h{n:02}'
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
        env = os.environ.copy()
        env['MANAGEMENT_PASSWORD'] = (self.root/'key.txt').read_text(encoding='utf-8').strip()
        subprocess.Popen([str(self.binary),'--config',str(folder/'config.yaml')], cwd=folder,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         close_fds=True, creationflags=flags,env=env)
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            if self.online(8400+n):
                return
            time.sleep(.2)
        raise ProviderError('CPA startup timeout', retryable=True)

    def _management(self,n,path,payload=None,timeout=20):
        key = (self.root/'key.txt').read_text(encoding='utf-8').strip()
        request = urllib.request.Request(f'http://127.0.0.1:{8400+n}/v0/management/{path}',
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=timeout) as r:
            return json.load(r)

    def refresh_quota(self,n):
        aid = f'h{n:02}'
        stats = {}
        try:
            self._config(n)
            self._boot(n)
            listing = self._management(n,'auth-files')
            files = [f for f in listing.get('files',[]) if f.get('provider')=='antigravity' or f.get('type')=='antigravity']
            if len(files)!=1 or not files[0].get('auth_index'):
                raise ValueError('Expected one management credential with auth_index')
            stats = {'identity_fingerprint':hashlib.sha256(str(files[0].get('email','')).encode()).hexdigest()[:16],
                     'provider_success':files[0].get('success'),'provider_failed':files[0].get('failed')}
            # The proxy refreshes expired OAuth tokens before substituting $TOKEN$.
            auth = json.loads(next((self.root/aid/'auth').glob('*.json')).read_text(encoding='utf-8'))
            result = self._management(n,'api-call',{'auth_index':files[0]['auth_index'],'method':'POST',
                'url':'https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary',
                'header':{'Authorization':'Bearer $TOKEN$','Content-Type':'application/json',
                          'User-Agent':UPSTREAM_UA},
                'data':json.dumps({'project':auth.get('project_id','')})})
            if result.get('status_code')!=200:
                raise ValueError('Quota upstream HTTP '+str(result.get('status_code')))
            fraction,reset,buckets = parse_quota(json.loads(result['body']))
            self.store.quota(aid,fraction,reset,buckets=buckets)
        except urllib.error.HTTPError as e:
            self.store.quota(aid,None,None,error=f'CPA management HTTP {e.code}')
        except Exception as e:
            detail = str(e) if isinstance(e,(ValueError,ProviderError)) and len(str(e))<150 else type(e).__name__
            self.store.quota(aid,None,None,error=detail)
        return {**self.store.quotas()[aid],**stats}

    def refresh_quotas(self):
        with ThreadPoolExecutor(max_workers=15) as executor:
            return list(executor.map(self.refresh_quota,range(1,16)))

    def _drop_identity(self, number):
        with self._identity_lock:
            self._identities.pop(number,None)
            self._epoch[number] = self._epoch.get(number,0)+1

    def _identity(self, number):
        """(auth_index, project_id) per account, cached; dropped on auth failure so a stale identity is never reused."""
        cached = self._identities.get(number)
        if cached and time.monotonic()<cached[2]:
            return cached[0],cached[1]
        aid = f'h{number:02}'
        epoch = self._epoch.get(number,0)
        listing = self._management(number,'auth-files').get('files',[])
        files = [f for f in listing if f.get('provider')=='antigravity' or f.get('type')=='antigravity']
        if len(files)!=1 or not files[0].get('auth_index'):
            raise ProviderError('Expected one generation credential')
        auth = json.loads(next((self.root/aid/'auth').glob('*.json')).read_text(encoding='utf-8'))
        with self._identity_lock:
            # A 401 that landed while we were listing makes this listing stale: use it once, do not cache it.
            if self._epoch.get(number,0)==epoch:
                self._identities[number] = (files[0]['auth_index'],auth['project_id'],time.monotonic()+600)
        return files[0]['auth_index'],auth['project_id']

    def complete(self, url, messages, max_tokens=4096, timeout=120, thinking_budget=None, reasoning_effort='low'):
        """CPA refresh/substitution with native Gemini generation; retains output and thinking limits.

        The installed CPA chat-completions executor deletes maxOutputTokens for Gemini.
        This explicit route never falls back to that unbounded translation path.
        """
        number=next((n for n in range(1,16) if url==f'http://127.0.0.1:{8400+n}'),None)
        if number is None:raise ValueError('Generation requires an assigned CPA loopback endpoint')
        if reasoning_effort not in ('low','medium','high'):
            raise ValueError('reasoning_effort must be low, medium, or high')
        budget=thinking_budget if thinking_budget is not None else {'low':512,'medium':1024,'high':2048}[reasoning_effort]
        if isinstance(budget,bool) or not isinstance(budget,int) or not 128<=budget<=32768:
            raise ValueError('thinking_budget must be an integer in 128..32768')
        if isinstance(max_tokens,bool) or not isinstance(max_tokens,int) or not 128<=max_tokens<=16384:
            raise ValueError('max_tokens must be an integer in 128..16384')
        system=[];contents=[]
        for message in messages:
            text=message['content'];role=message['role']
            if not isinstance(text,str):raise ValueError('Only explicit text messages are supported')
            if role=='system':system.append({'text':text})
            elif role in ('user','assistant'):
                contents.append({'role':'model' if role=='assistant' else 'user','parts':[{'text':text}]})
            else:raise ValueError('Unsupported message role')
        request={'contents':contents,'sessionId':'-'+str(uuid.uuid4().int%10**18),
                 'generationConfig':{'temperature':.1,'maxOutputTokens':max_tokens,
                     'responseMimeType':'application/json','thinkingConfig':{'thinkingBudget':min(budget,max_tokens-1)}}}
        if system:request['systemInstruction']={'parts':system}
        aid=f'h{number:02}';usage=None;success=False;sent=False
        try:
            auth_index,project=self._identity(number)
            body={'project':project,'model':self.model,'userAgent':'antigravity','requestType':'agent',
                  'requestId':'agent-'+str(uuid.uuid4()),'request':request}
            self.store.generation_start(aid);sent=True
            result=self._management(number,'api-call',{'auth_index':auth_index,'method':'POST',
                'url':'https://daily-cloudcode-pa.googleapis.com/v1internal:generateContent',
                'header':{'Authorization':'Bearer $TOKEN$','Content-Type':'application/json',
                          'User-Agent':UPSTREAM_UA},'data':json.dumps(body)},timeout=timeout)
            if result.get('status_code')!=200:
                status=result.get('status_code')
                if status in (401,403):
                    self._drop_identity(number)
                raise ProviderError(f'Generation HTTP {status}',status in (401,403,429) or isinstance(status,int) and status>=500,
                                    300 if status==429 else 900 if status in (401,403) else 30)
            raw=json.loads(result['body']);data=raw.get('response',raw)
            metadata=data.get('usageMetadata',{})
            total=metadata.get('totalTokenCount')
            if isinstance(total,int) and not isinstance(total,bool) and total>=0:
                usage={'total_tokens':total,'prompt_tokens':metadata.get('promptTokenCount',0),
                       'completion_tokens':metadata.get('candidatesTokenCount',0)+metadata.get('thoughtsTokenCount',0),
                       'completion_tokens_details':{'reasoning_tokens':metadata.get('thoughtsTokenCount',0)},
                       'provider_model':data.get('modelVersion'),'transport':'native-cpa-api-call'}
            choice=data['candidates'][0]
            if choice.get('finishReason')=='MAX_TOKENS':
                raise ProviderError('Model output token limit reached',True,usage=usage)
            if choice.get('finishReason')!='STOP':
                raise ProviderError('Model response did not complete',True,usage=usage)
            content=''.join(p.get('text','') for p in choice['content'].get('parts',[]) if not p.get('thought'))
            if not content.strip():
                raise ProviderError('Empty model response',True,usage=usage)
            success=True
            return content, usage
        except urllib.error.HTTPError as e:
            status = e.code
            if status in (401,403):
                self._drop_identity(number)
            if status == 429:
                raise ProviderError('HTTP 429 quota', True, 300) from None
            if status in (401,403):
                raise ProviderError(f'HTTP {status} authentication', True, 900) from None
            raise ProviderError(f'HTTP {status}', status>=500, 30 if status>=500 else 0) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderError('Provider connection/timeout', True, 30) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError('Invalid provider response',usage=usage) from None
        finally:
            if sent:self.store.generation_finish(aid,success,usage)
