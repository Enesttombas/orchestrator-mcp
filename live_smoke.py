"""Explicit finite live acceptance: 15 pinned accounts + dependent integration through actual MCP stdio.

No user project is sent. Only generated, synthetic task descriptions and fixture tests cross the network.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from test_orchestrator import Wire

CASES = [
 ('gcd','Implement gcd(a,b) for signed integers. Always return nonnegative gcd; gcd(0,0)=0.',
  'assert m.gcd(48,18)==6\nassert m.gcd(-12,8)==4\nassert m.gcd(0,0)==0'),
 ('unique','Implement unique(values), preserving first occurrence order for hashable values.',
  'assert m.unique([3,1,3,2,1])==[3,1,2]\nassert m.unique([])==[]'),
 ('balanced','Implement balanced(text) for (), [], {} nesting; ignore other characters.',
  'assert m.balanced("{a[()]}")\nassert not m.balanced("([)]")\nassert not m.balanced("(")\nassert m.balanced("")'),
 ('chunks','Implement chunks(values,size): list of chunks, last may be short; size<=0 raises ValueError.',
  'assert m.chunks([1,2,3,4,5],2)==[[1,2],[3,4],[5]]\nassert m.chunks([],3)==[]\ntry:\n m.chunks([1],0)\nexcept ValueError: pass\nelse: raise AssertionError("must reject zero")'),
 ('runs','Implement runs(text): run-length encode as a list of (character,count) tuples.',
  'assert m.runs("aaabbca")==[("a",3),("b",2),("c",1),("a",1)]\nassert m.runs("")==[]'),
 ('transpose','Implement transpose(rows), returning list-of-lists. Empty input returns []; ragged rows raise ValueError.',
  'assert m.transpose([[1,2],[3,4]])==[[1,3],[2,4]]\nassert m.transpose([])==[]\ntry:\n m.transpose([[1],[2,3]])\nexcept ValueError: pass\nelse: raise AssertionError("ragged")'),
 ('merge_intervals','Implement merge_intervals(intervals): sorted list of merged [start,end] pairs; touching intervals merge.',
  'assert m.merge_intervals([[5,7],[1,3],[3,6],[10,11]])==[[1,7],[10,11]]\nassert m.merge_intervals([])==[]'),
 ('rotate','Implement rotate(values,k): rotate list right by k, supporting negative k and empty lists.',
  'assert m.rotate([1,2,3,4],1)==[4,1,2,3]\nassert m.rotate([1,2,3],-1)==[2,3,1]\nassert m.rotate([],20)==[]'),
 ('binary_search','Implement binary_search(values,target): first index of target in sorted values, else -1.',
  'assert m.binary_search([1,2,2,2,4],2)==1\nassert m.binary_search([],1)==-1\nassert m.binary_search([1,3],2)==-1'),
 ('flatten','Implement flatten(values): recursively flatten nested lists only; other values are leaves.',
  'assert m.flatten([1,[2,[],[3]],"xy"])==[1,2,3,"xy"]\nassert m.flatten([])==[]'),
 ('is_prime','Implement is_prime(n) for integers, returning boolean.',
  'assert m.is_prime(97)\nassert not m.is_prime(1)\nassert not m.is_prime(-7)\nassert not m.is_prime(49)\nassert m.is_prime(2)'),
 ('median','Implement median(values), without mutating input. Empty input raises ValueError.',
  'a=[9,1,3];assert m.median(a)==3;assert a==[9,1,3]\nassert m.median([4,1,3,2])==2.5\ntry:\n m.median([])\nexcept ValueError: pass\nelse: raise AssertionError("empty")'),
 ('word_counts','Implement word_counts(text): lowercase whitespace-delimited word frequency; punctuation stays part of word.',
  'assert m.word_counts("A b A\\nb")=={"a":2,"b":2}\nassert m.word_counts("")=={}'),
 ('lcp','Implement lcp(strings): longest common prefix; [] returns empty string.',
  'assert m.lcp(["flower","flow","flight"])=="fl"\nassert m.lcp([])==""\nassert m.lcp(["abc",""])==""'),
 ('two_sum','Implement two_sum(values,target): distinct indices (i,j), i<j, whose values sum to target; return None if absent.',
  'assert m.two_sum([3,3],6)==(0,1)\nr=m.two_sum([2,7,11,15],9);assert r==(0,1)\nassert m.two_sum([],2) is None'),
]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--entry',type=Path)
    args=parser.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    fixture=root/'fixture';fixture.mkdir()
    wire=Wire(root,enabled=True,entry=args.entry)
    start=time.time()
    try:
        sid=wire.call('orchestrator_init',goal='Finite live 15-account code acceptance',mode='custom_dag',
                      max_iterations=32,work_dir=str(fixture))['session_id']
        parents=[]
        for n,(name,brief,checks) in enumerate(CASES,1):
            tid=f'T{n:02}';module=f'solution_{n:02}';check=f'check_{n:02}.py'
            (fixture/check).write_text(f'import {module} as m\n'+checks+'\n',encoding='utf-8')
            wire.call('orchestrator_add_task',session_id=sid,task_id=tid,role='worker',title=name,
                      description=brief+f' Write {module}.py. Standard library only.')
            wire.call('orchestrator_configure_task',session_id=sid,task_id=tid,
                      context_files=[check],output_files=[module+'.py'],
                      acceptance_command=[sys.executable,check],account_id=f'h{n:02}',max_tokens=2048,max_attempts=2)
            parents.append(tid)
        integration='import runpy\n'+''.join(f'runpy.run_path("check_{n:02}.py")\n' for n in range(1,16))
        (fixture/'integration.py').write_text(integration,encoding='utf-8')
        wire.call('orchestrator_add_task',session_id=sid,task_id='INTEGRATE',role='reviewer',
                  title='All outputs together',description='Summarize the purpose of testing all 15 outputs together. files must be {}.',dependencies=parents)
        wire.call('orchestrator_configure_task',session_id=sid,task_id='INTEGRATE',context_files=[
            'integration.py']+[f'check_{n:02}.py' for n in range(1,16)],output_files=[],
            acceptance_command=[sys.executable,'integration.py'],max_tokens=512,max_attempts=1)
        launched=wire.call('orchestrator_run_session',session_id=sid,parallel=15)
        duplicate=wire.call('orchestrator_run_session',session_id=sid,parallel=15)
        assert duplicate['status']=='already_running'
        print(json.dumps({'session_id':sid,'runner':launched,'restart_client':True}),flush=True)
        wire.close();wire=Wire(root,enabled=True,entry=args.entry)
        deadline=time.monotonic()+360
        previous=None
        while time.monotonic()<deadline:
            state=wire.call('orchestrator_get_status',session_id=sid,format='json')
            counts={status:sum(t['status']==status for t in state['tasks']) for status in
                    ('PENDING','IN_PROGRESS','COMPLETED','FAILED','SKIPPED')}
            if counts!=previous:
                print(json.dumps(counts),flush=True);previous=counts
            if not state['runner']['active']:
                break
            time.sleep(2)
        else:
            wire.call('orchestrator_cancel_session',session_id=sid)
            raise TimeoutError('Finite live run deadline exceeded')
        rows=[]
        for t in state['tasks']:
            evidence=json.loads(t['evidence'] or '{}')
            rows.append({'task_id':t['task_id'],'status':t['status'],'account_id':t['account_id'],
                         'attempts':t['attempts'],'exit_code':t['exit_code'],'error':t['error'],
                         'model_seconds':evidence.get('model_seconds'),'usage':evidence.get('usage'),
                         'evidence_path':t['artifact_path']})
        success=state['session']['status']=='COMPLETED'
        assert len({r['account_id'] for r in rows[:15]})==15,rows
        result={'session_id':sid,'success':success,'seconds':round(time.time()-start,2),
                'client_restart':True,'duplicate_run_prevented':True,'tasks':rows}
        (root/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
        if not success:return 1
        # Deliberately apply a single accepted output to this synthetic fixture and rerun its test.
        applied=wire.call('orchestrator_apply_task',session_id=sid,task_id='T01')
        assert applied['files']==['solution_01.py']
        check=subprocess.run([sys.executable,'check_01.py'],cwd=fixture,check=False)
        assert check.returncode==0
        return 0
    finally:wire.close()


if __name__=='__main__':
    import subprocess
    sys.exit(main())
