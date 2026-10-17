"""Additional seeded properties, never fed to generation or repair prompts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP
import importlib
import json
from pathlib import Path
import random
import sys
import tempfile

def main():
    p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--workspace',type=Path,required=True)
    a=p.parse_args();sys.path.insert(0,str(a.workspace.resolve()))
    rng=random.Random(871240);checks=0
    storage=importlib.import_module('storage');pricing=importlib.import_module('pricing')
    with tempfile.TemporaryDirectory() as tmp:
        db=str(Path(tmp)/'state.db')
        if a.case=='booking':
            s=storage.Inventory(db);s.set_stock('Z',37)
            for n in range(100):
                q=rng.randint(1,100);price=str(Decimal(rng.randint(0,100000))/1000);d=rng.randint(0,100)
                expected=str((q*Decimal(price)*(1-Decimal(d)/100)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                assert pricing.quote(q,price,d)==expected;checks+=1
            with ThreadPoolExecutor(max_workers=15) as ex:
                taken=list(ex.map(lambda n:storage.Inventory(db).reserve(str(n),'Z',3),range(40)))
            assert sum(taken)==12 and s.available('Z')==1;checks+=1
            with ThreadPoolExecutor(max_workers=15) as ex:
                released=list(ex.map(lambda _:storage.Inventory(db).release(str(taken.index(True))),range(25)))
            assert sum(released)==1 and s.available('Z')==4;checks+=1
        elif a.case=='ledger':
            s=storage.Ledger(db);s.post('seed','A',53,'TRY')
            for n in range(100):
                value=rng.choice([-1,1])*rng.randint(1,10**18)
                text=('-' if value<0 else '')+str(abs(value)//100)+'.'+str(abs(value)%100).zfill(2)
                assert pricing.format_cents(value)==text;assert pricing.cents(text)==value;checks+=2
            def move(n):
                try:return storage.Ledger(db).transfer(str(n),'A','B',7,'TRY')
                except ValueError:return False
            with ThreadPoolExecutor(max_workers=15) as ex:success=list(ex.map(move,range(40)))
            assert sum(success)==7 and s.balance('A','TRY')==4 and s.balance('B','TRY')==49;checks+=1
        elif a.case=='queue':
            q=storage.Queue(db)
            for n in range(21):q.enqueue(str(n).zfill(2),'K',{'v':n},n%3)
            first=[]
            for n in range(21):
                job=q.claim('old',0,5);first.append(job)
            assert [j['priority'] for j in first]==sorted([n%3 for n in range(21)],reverse=True);checks+=1
            with ThreadPoolExecutor(max_workers=15) as ex:
                second=list(ex.map(lambda n:storage.Queue(db).claim(str(n),5,10),range(40)))
            second=[j for j in second if j]
            assert len(second)==21 and len({j['id'] for j in second})==21;checks+=1
            for j in second:
                assert not q.finish(j['id'],'old',1,6);assert q.finish(j['id'],j['owner'],2,6);checks+=2
            for n in range(100):
                attempt=rng.randint(1,30);base=rng.randint(1,10);cap=rng.randint(1,1000)
                assert pricing.delay(attempt,base,cap)==min(cap,base*2**(attempt-1));checks+=1
        else:raise ValueError('Unknown case')
    print(json.dumps({'case':a.case,'seed':871240,'assertions':checks,'passed':True}))
    return 0

if __name__=='__main__':sys.exit(main())
