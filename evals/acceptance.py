"""Hidden functional/transactional tests. Do not include this file in model context."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'state.db')
    def tearDown(self):self.tmp.cleanup()
    def mod(self,name):return importlib.import_module(name)
    def rejects(self,func,values):
        for args in values:
            with self.subTest(args=args),self.assertRaises(ValueError):func(*args)

class Booking(Tests):
    def test_validation_normalizes_without_mutation(self):
        d={'id':' A ','sku':' X ','quantity':2,'unit_price':'0.335','extra':1};old=d.copy()
        r=self.mod('validation').normalize(d)
        self.assertEqual(r,{'id':'A','sku':'X','quantity':2,'unit_price':'0.335','discount':'0'});self.assertEqual(d,old)
    def test_validation_rejects_types_and_missing(self):
        good={'id':'A','sku':'X','quantity':1,'unit_price':'1'}
        vals=[(None,),([],),({},)]+[({**good,'quantity':q},) for q in [True,0,-1,'2',1.2]]+[
            ({**good,'id':''},),({**good,'sku':2},)]
        self.rejects(self.mod('validation').normalize,vals)
    def test_pricing_decimal_rounding_and_discount(self):
        f=self.mod('pricing').quote
        for args,expected in [((3,'0.335'),'1.01'),((2,'10','12.5'),'17.50'),((1,'2.675'),'2.68'),
            ((5,'9.99','100'),'0.00'),((2,'0'),'0.00'),((1,'100000000000.01'),'100000000000.01')]:
            with self.subTest(args=args):self.assertEqual(f(*args),expected)
    def test_pricing_invalid(self):
        self.rejects(self.mod('pricing').quote,[(True,'1'),(0,'1'),(1,'NaN'),(1,'Infinity'),(1,'-1'),
            (1,'1','101'),(1,'1','-1'),(1,True),(1,'1',True)])
    def test_storage_idempotency_release_persistence(self):
        C=self.mod('storage').Inventory;s=C(self.db);s.set_stock('X',5)
        self.assertTrue(s.reserve('a','X',2));self.assertTrue(s.reserve('a','X',2));self.assertEqual(s.available('X'),3)
        self.assertFalse(s.reserve('b','X',4));self.assertTrue(s.reserve('b','X',3))
        self.assertTrue(s.release('a'));self.assertFalse(s.release('a'));self.assertFalse(s.release('missing'))
        self.assertEqual(C(self.db).available('X'),2)
        self.rejects(s.reserve,[('a','X',2),('b','X',2),('c','NO',1)])
    def test_storage_invalid(self):
        s=self.mod('storage').Inventory(self.db);s.set_stock('X',1)
        self.rejects(s.set_stock,[('X',1),('Y',True),('Y',-1)])
        self.rejects(s.reserve,[('a','X',True),('a','X',0),('a','X',-1)])
        self.assertEqual(s.available('X'),1)
    def test_storage_concurrent_no_oversell(self):
        C=self.mod('storage').Inventory;C(self.db).set_stock('X',7)
        with ThreadPoolExecutor(max_workers=16) as ex:
            results=list(ex.map(lambda n:C(self.db).reserve(str(n),'X',1),range(40)))
        self.assertEqual(sum(results),7);self.assertEqual(C(self.db).available('X'),0)
    def test_reporting_grouping_precision_order(self):
        rows=[{'day':'2026-02-02','quantity':1,'total':'0.10','status':'active'},
              {'day':'2026-02-01','quantity':2,'total':'0.20','status':'active'},
              {'day':'2026-02-02','quantity':3,'total':'0.20','status':'active'},
              {'day':'2026-02-01','quantity':99,'total':'99','status':'cancelled'}]
        original=json.dumps(rows);self.assertEqual(self.mod('reporting').daily(rows),[
            {'day':'2026-02-01','bookings':1,'quantity':2,'revenue':'0.20'},
            {'day':'2026-02-02','bookings':2,'quantity':4,'revenue':'0.30'}])
        self.assertEqual(json.dumps(rows),original);self.assertEqual(self.mod('reporting').daily([]),[])
    def test_service_workflow(self):
        s=self.mod('storage').Inventory(self.db);s.set_stock('X',3);b=self.mod('service').Booker(s)
        data={'id':' A ','sku':' X ','quantity':2,'unit_price':'0.335'}
        expected={'id':'A','sku':'X','quantity':2,'total':'0.67','status':'active'}
        self.assertEqual(b.book(data),expected);self.assertEqual(b.book(data),expected)
        self.assertEqual(s.available('X'),1);self.assertIsNone(b.book({**data,'id':'B'}))
        self.assertTrue(b.cancel('A'));self.assertEqual(s.available('X'),3)
    def test_service_invalid_price_does_not_reserve(self):
        s=self.mod('storage').Inventory(self.db);s.set_stock('X',3);b=self.mod('service').Booker(s)
        self.rejects(b.book,[({'id':'a','sku':'X','quantity':1,'unit_price':'NaN'},)])
        self.assertEqual(s.available('X'),3)

class Ledger(Tests):
    def test_validation_currency_and_input(self):
        d={'id':' A ','account':' x ','amount':'1.005','currency':' usd ','other':1};original=d.copy()
        self.assertEqual(self.mod('validation').normalize(d),{'id':'A','account':'x','amount':'1.005','currency':'USD'})
        self.assertEqual(d,original)
    def test_validation_invalid(self):
        good={'id':'a','account':'x','amount':'1','currency':'USD'}
        self.rejects(self.mod('validation').normalize,[(None,),({},),({**good,'currency':'JPY'},),
            ({**good,'account':3},),({**good,'id':' '},)])
    def test_pricing_signed_and_large(self):
        p=self.mod('pricing')
        for n,c in [('1.005',101),('-1.005',-101),('100000000000000.01',10000000000000001)]:self.assertEqual(p.cents(n),c)
        for n,text in [(101,'1.01'),(-1,'-0.01'),(10000000000000001,'100000000000000.01')]:self.assertEqual(p.format_cents(n),text)
    def test_pricing_invalid(self):
        p=self.mod('pricing');self.rejects(p.cents,[(True,),('NaN',),('inf',),('0',),('0.001',),('',)])
        self.rejects(p.format_cents,[(True,),(1.2,)])
    def test_storage_atomic_transfer_and_idempotency(self):
        C=self.mod('storage').Ledger;s=C(self.db)
        self.assertTrue(s.post('a','alice',100,'USD'));self.assertFalse(s.post('a','alice',100,'USD'))
        self.assertTrue(s.transfer('a','alice','bob',60,'USD'));self.assertFalse(s.transfer('a','alice','bob',60,'USD'))
        self.assertEqual(C(self.db).balance('alice','USD'),40);self.assertEqual(s.balance('bob','USD'),60)
        self.rejects(s.transfer,[('b','alice','bob',50,'USD'),('a','alice','bob',30,'USD')])
        self.assertEqual(s.balance('alice','USD'),40);self.assertEqual(s.balance('none','USD'),0)
    def test_storage_invalid_and_conflicts(self):
        s=self.mod('storage').Ledger(self.db);s.post('a','alice',100,'USD')
        self.rejects(s.post,[('a','alice',101,'USD'),('b','alice',True,'USD'),('b','alice',0,'USD'),('b','',1,'USD'),('b','a',1,'JPY')])
        self.rejects(s.transfer,[('t','alice','alice',1,'USD'),('t','alice','bob',True,'USD'),('t','alice','bob',0,'USD')])
    def test_storage_concurrent_no_overdraft(self):
        C=self.mod('storage').Ledger;s=C(self.db);s.post('seed','alice',1000,'USD')
        def take(n):
            try:return C(self.db).transfer(str(n),'alice','bob',100,'USD')
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=16) as ex:results=list(ex.map(take,range(30)))
        self.assertEqual(sum(results),10);self.assertEqual(s.balance('alice','USD'),0);self.assertEqual(s.balance('bob','USD'),1000)
    def test_reporting_group_sort_no_mutation(self):
        rows=[{'account':'b','currency':'USD','amount_cents':1},{'account':'a','currency':'TRY','amount_cents':8},
              {'account':'b','currency':'USD','amount_cents':-4}];before=json.dumps(rows)
        self.assertEqual(self.mod('reporting').summarize(rows),[{'account':'a','currency':'TRY','balance_cents':8,'entries':1},
            {'account':'b','currency':'USD','balance_cents':-3,'entries':2}])
        self.assertEqual(json.dumps(rows),before);self.assertEqual(self.mod('reporting').summarize([]),[])
    def test_service_integration(self):
        s=self.mod('storage').Ledger(self.db);a=self.mod('service').Accounting(s)
        p={'id':'x','account':'alice','amount':'1.005','currency':' usd '}
        self.assertTrue(a.post(p));self.assertFalse(a.post(p));self.assertEqual(s.balance('alice','USD'),101)
        self.assertTrue(a.transfer('t','alice','bob','0.005',' usd '));self.assertEqual(s.balance('bob','USD'),1)
    def test_service_bad_money_leaves_no_posting(self):
        s=self.mod('storage').Ledger(self.db);a=self.mod('service').Accounting(s)
        self.rejects(a.post,[({'id':'x','account':'a','amount':'NaN','currency':'USD'},)])
        self.assertEqual(s.balance('a','USD'),0)

class Queue(Tests):
    def test_validation_deep_copy_defaults(self):
        d={'id':' a ','kind':' k ','payload':{'nested':[1]}};r=self.mod('validation').normalize(d)
        self.assertEqual(r,{'id':'a','kind':'k','payload':{'nested':[1]},'priority':0})
        r['payload']['nested'].append(2);self.assertEqual(d['payload']['nested'],[1])
    def test_validation_invalid_json_and_priority(self):
        good={'id':'a','kind':'k'}
        self.rejects(self.mod('validation').normalize,[(None,),({},),({**good,'priority':True},),
            ({**good,'priority':101},),({**good,'payload':{'x':float('nan')}},),({**good,'payload':{'x':set()}},)])
    def test_pricing_exponential_is_bounded(self):
        p=self.mod('pricing');self.assertEqual(p.delay(1),1);self.assertEqual(p.delay(4,3,10),10)
        start=time.monotonic();self.assertEqual(p.delay(10**9),60);self.assertLess(time.monotonic()-start,.5)
        self.assertEqual(p.ready_at(1.5,2),3.5)
    def test_pricing_invalid(self):
        p=self.mod('pricing');self.rejects(p.delay,[(True,),(0,),(-1,),(1,0),(1,1,False)])
        self.rejects(p.ready_at,[(True,1),(float('inf'),1)])
    def test_storage_priority_fencing_persistence(self):
        C=self.mod('storage').Queue;q=C(self.db)
        self.assertTrue(q.enqueue('b','k',{'x':1},1));self.assertFalse(q.enqueue('b','k',{'x':1},1))
        q.enqueue('a','k',{},1);job=q.claim('one',100,5);self.assertEqual(job['id'],'a');self.assertEqual(job['attempt'],1)
        self.assertFalse(q.finish('a','bad',1,101));self.assertFalse(q.finish('a','one',1,105))
        nextjob=C(self.db).claim('two',105,5);self.assertEqual(nextjob['id'],'a');self.assertEqual(nextjob['attempt'],2)
        self.assertFalse(q.finish('a','one',1,106));self.assertTrue(q.finish('a','two',2,106));self.assertFalse(q.finish('a','two',2,106))
        self.assertEqual(C(self.db).get('a')['state'],'completed');self.assertEqual(q.claim('three',106)['id'],'b')
    def test_storage_invalid(self):
        q=self.mod('storage').Queue(self.db);q.enqueue('a','k',{})
        self.rejects(q.enqueue,[('a','other',{}),('b','k',{},True),('','k',{})])
        self.rejects(q.claim,[('',0),('x',float('nan')),('x',0,0),('x',True)])
    def test_storage_atomic_concurrent_claim(self):
        C=self.mod('storage').Queue;q=C(self.db)
        for n in range(12):q.enqueue(f'{n:02}','k',{})
        with ThreadPoolExecutor(max_workers=16) as ex:jobs=list(ex.map(lambda n:C(self.db).claim(str(n),100),range(30)))
        ids=[j['id'] for j in jobs if j];self.assertEqual(len(ids),12);self.assertEqual(len(set(ids)),12)
    def test_reporting_counts_and_rejects(self):
        f=self.mod('reporting').summarize
        self.assertEqual(f([{'state':'pending','attempt':0},{'state':'running','attempt':2},{'state':'completed','attempt':1}]),
            {'pending':1,'running':1,'completed':1,'total':3,'attempts':3})
        self.assertEqual(f([]),{'pending':0,'running':0,'completed':0,'total':0,'attempts':0})
        self.rejects(f,[([{'state':'unknown','attempt':0}],)])
    def test_service_success_failure_and_retry(self):
        q=self.mod('storage').Queue(self.db);Worker=self.mod('service').Worker
        w=Worker(q,'one',{'ok':lambda p:p['x']+1,'bad':lambda p:1/0})
        w.submit({'id':'a','kind':'ok','payload':{'x':2}});self.assertEqual(w.tick(100),{'id':'a','status':'completed','result':3})
        w.submit({'id':'b','kind':'bad'});self.assertEqual(w.tick(100,5),{'id':'b','status':'failed'})
        self.assertEqual(q.get('b')['state'],'running');self.assertIsNone(w.tick(101))
        self.assertEqual(w.tick(105,5),{'id':'b','status':'failed'});self.assertEqual(q.get('b')['attempt'],2)
    def test_service_unknown_and_stale(self):
        q=self.mod('storage').Queue(self.db);w=self.mod('service').Worker(q,'one',{})
        w.submit({'id':'a','kind':'unknown'});self.assertEqual(w.tick(100),{'id':'a','status':'failed'})
        class Stale:
            def claim(self,owner,now,lease_seconds=30):return {'id':'b','kind':'ok','payload':{},'attempt':1}
            def finish(self,job_id,owner,attempt,now):return False
        self.assertEqual(self.mod('service').Worker(Stale(),'x',{'ok':lambda p:1}).tick(1),{'id':'b','status':'stale'})

def main():
    p=argparse.ArgumentParser();p.add_argument('--case',required=True,choices=['booking','ledger','queue'])
    p.add_argument('--part',default='all');p.add_argument('--workspace',default='.')
    a=p.parse_args();sys.path.insert(0,str(Path(a.workspace).resolve()))
    cls={'booking':Booking,'ledger':Ledger,'queue':Queue}[a.case]
    names=unittest.defaultTestLoader.getTestCaseNames(cls)
    selected=[n for n in names if a.part=='all' or n.startswith('test_'+a.part+'_')]
    if not selected:raise ValueError('No tests selected')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(cls(n) for n in selected))
    print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)}))
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':sys.exit(main())
