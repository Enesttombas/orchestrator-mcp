"""Finite paired live evaluation through installed MCP, with frozen hidden checks.

Each arm gets the same contracts/model/temperature and two acceptance attempts.
No prompts or source from the user's projects are sent. This is not a general quality guarantee.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from execution import acceptance, parse_response
from pool import Pool
from store import Store
from runner import SYSTEM
from test_orchestrator import Wire
from cases import CASES,PARTS

CHECK=Path(__file__).with_name('acceptance.py').resolve()
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def check(case,workspace,part='all'):
    return acceptance([sys.executable,str(CHECK),'--case',case,'--part',part],workspace,60)

def baseline(case,root,entry):
    root.mkdir();workspace=root/'workspace';workspace.mkdir()
    started=time.monotonic()
    store=Store(root/'state.db');pool=Pool(store);pool.refresh_quotas()
    description='Implement this complete standard-library-only Python project.\n'+'\n\n'.join(CASES[case].values())
    calls=[];feedback=None;ev=None
    for attempt in range(1,3):
        if attempt>1:pool.refresh_quotas()
        messages=[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({
            'task':description,'role':'worker','allowed_output_files':[p+'.py' for p in PARTS],
            'context_files':{p.name:p.read_text(encoding='utf-8') for p in workspace.glob('*.py')},
            'previous_attempt_feedback':feedback})}]
        t=time.monotonic();usage=None;error=None;aid=None
        try:
            with pool.acquire() as (aid,url):
                content,usage=pool.complete(url,messages,max_tokens=16384,reasoning_effort='low' if attempt==1 else 'high')
            _,files=parse_response(content,[p+'.py' for p in PARTS])
            for name,text in files.items():(workspace/name).write_text(text,encoding='utf-8')
            ev=check(case,workspace)
            if ev['exit_code']:
                feedback={'error':'Acceptance command failed','exit_code':ev['exit_code'],
                          'acceptance_log_tail':Path(ev['log']).read_text(encoding='utf-8')[-4000:]}
        except Exception as e:
            error=str(e) if type(e).__name__=='ProviderError' else type(e).__name__
            feedback={'error':error};ev={'exit_code':None}
        calls.append({'attempt':attempt,'account_id':aid,'reasoning_effort':'low' if attempt==1 else 'high','seconds':round(time.monotonic()-t,3),
                      'usage':usage,'error':error,'acceptance':ev})
        write(root/'calls.json',calls)
        if ev['exit_code']==0:break
    result={'arm':'single_call','case':case,'seconds':round(time.monotonic()-started,3),
            'success':ev['exit_code']==0,'first_pass':calls[0]['acceptance']['exit_code']==0,
            'calls':calls,'final_acceptance':ev}
    write(root/'result.json',result);return result

def mcp(case,root,entry):
    root.mkdir();workspace=root/'workspace';workspace.mkdir()
    wire=Wire(root,enabled=True,entry=entry)
    start=time.monotonic();peak=0
    try:
        sid=wire.call('orchestrator_init',goal='Synthetic quality evaluation: '+case,mode='custom_dag',
                      max_iterations=10,work_dir=str(workspace))['session_id']
        for part in PARTS:
            contract=part+'.md';(workspace/contract).write_text(CASES[case][part],encoding='utf-8')
            wire.call('orchestrator_add_task',session_id=sid,task_id=part,role='worker',title=part,
                      description='Implement '+part+'.py according to '+contract+'. Standard library only.',
                      dependencies=list(PARTS[:4]) if part=='service' else [])
            wire.call('orchestrator_configure_task',session_id=sid,task_id=part,
                      context_files=[contract],
                      output_files=[part+'.py'],acceptance_command=[sys.executable,str(CHECK),'--case',case,'--part',part],
                      timeout=60,max_tokens=8192 if part=='storage' else 4096,max_attempts=2)
        launched=wire.call('orchestrator_run_session',session_id=sid,parallel=15)
        deadline=time.monotonic()+480
        while time.monotonic()<deadline:
            state=wire.call('orchestrator_get_status',session_id=sid,format='json')
            peak=max(peak,sum(t['status']=='IN_PROGRESS' for t in state['tasks']))
            if not state['runner']['active']:break
            time.sleep(.25)
        else:
            wire.call('orchestrator_cancel_session',session_id=sid)
            raise TimeoutError('Bounded evaluation deadline')
        rows=[];assembled=root/'assembled';assembled.mkdir()
        for task in state['tasks']:
            ev=json.loads(task.get('evidence') or '{}')
            rows.append({'task_id':task['task_id'],'status':task['status'],'attempts':task['attempts'],
                         'error':task['error'],'evidence':ev})
            for name,item in ev.get('outputs',{}).items():shutil.copyfile(item['path'],assembled/name)
        final=check(case,assembled)
        calls=[json.loads(p.read_text(encoding='utf-8')) for p in (root/'artifacts'/sid).glob('*_model-call.json')]
        result={'arm':'mcp','case':case,'session_id':sid,'seconds':round(time.monotonic()-start,3),
                'success':state['session']['status']=='COMPLETED' and final['exit_code']==0,
                'first_pass':all(t['attempts']==1 and t['status']=='COMPLETED' for t in rows),
                'peak_in_progress':peak,'calls':calls,'tasks':rows,'final_acceptance':final}
        write(root/'result.json',result);return result
    finally:wire.close()

def totals(result):
    usages=[c.get('usage') for c in result['calls']]
    result['tokens_complete']=all(isinstance(u,dict) and 'total_tokens' in u for u in usages)
    for key in ('prompt_tokens','completion_tokens','total_tokens'):
        result[key]=sum(u.get(key,0) for u in usages if isinstance(u,dict)) if result['tokens_complete'] else None
    result['call_count']=len(usages)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--entry',type=Path,required=True);p.add_argument('--cases',nargs='+',default=list(CASES))
    a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    os.environ['ORCHESTRATOR_GEMINI_ENABLED']='1';os.environ['ORCHESTRATOR_ARTIFACTS_DIR']=str(root/'baseline-artifacts')
    source_root=Path(__file__).resolve().parents[1]
    frozen={str(p.relative_to(source_root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_root.rglob('*.py')}
    write(root/'frozen-before.json',{'sha256':frozen,'model':'gemini-3.8-flash-high','temperature':.1,
        'max_attempts':2,'reasoning_policy':'low first; high on rejected attempt',
        'model_sees_acceptance_source':False,'started_at':time.time()})
    results=[]
    for n,case in enumerate(a.cases):
        for arm in (('single_call','mcp') if n%2==0 else ('mcp','single_call')):
            print(json.dumps({'starting':case,'arm':arm}),flush=True)
            func=baseline if arm=='single_call' else mcp
            result=totals(func(case,root/(case+'-'+arm),a.entry))
            write(root/(case+'-'+arm)/'result.json',result)
            results.append(result);write(root/'results.json',results)
            print(json.dumps({k:result[k] for k in ('case','arm','seconds','success','first_pass','call_count','total_tokens')}),flush=True)
    return 0 if all(r['success'] for r in results) else 1

if __name__=='__main__':sys.exit(main())
