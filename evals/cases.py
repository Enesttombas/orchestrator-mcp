"""Frozen API contracts. The model never receives the separate acceptance implementation."""
CASES={
'booking':{
'validation':'''validation.py: normalize(data) -> dict with only id, sku, quantity, unit_price, discount.
data must be dict. id and sku must be nonempty strings after strip; normalize with strip only.
quantity must be an integer >0; booleans invalid. unit_price and discount are left unchanged for pricing;
default discount='0'. Missing required id/sku/quantity/unit_price or invalid input raises ValueError.
Ignore unknown keys. Do not mutate input.''',
'pricing':'''pricing.py: quote(quantity, unit_price, discount='0') -> decimal monetary string with 2 digits.
quantity positive int, bool invalid. Prices/discount accept strings, ints, floats, Decimal, but NOT bool.
Use Decimal(str(value)); reject NaN/infinity, negative price, discount outside [0,100]. Invalid input raises
ValueError. total = quantity*unit_price*(1-discount/100), rounded once at end with ROUND_HALF_UP.
Examples quote(3,'0.335')='1.01', quote(2,'10','12.5')='17.50'.''',
'storage':'''storage.py: class Inventory(path), SQLite persistent storage. Each instance may be used across threads.
set_stock(sku,quantity): set nonnegative integer inventory for a new SKU; overwriting an existing SKU raises
ValueError; bool invalid. available(sku) -> int, unknown SKU raises ValueError.
reserve(booking_id,sku,quantity) -> bool: positive int quantity (bool invalid); atomically deduct only if
enough stock. Insufficient stock returns False without creating reservation. Repeating same booking_id
with same sku/quantity returns True without deducting again. Same id with different arguments raises
ValueError. Unknown SKU raises ValueError. release(booking_id) -> bool: once-only refund if active;
unknown/already released returns False. Released booking ids cannot be reused: reserve raises ValueError.
Use atomic transactions so simultaneous reservations never oversell. Persist across new instances.
All invalid numeric inputs raise ValueError. No network/global singleton database.''',
'reporting':'''reporting.py: daily(records) -> list of dicts sorted lexicographically by day.
Records are dicts with day string, quantity integer, total decimal string and status ('active' or 'cancelled').
Only active records count. Each result has day, bookings (count), quantity (sum), revenue (sum totals,
2 decimal ROUND_HALF_UP string). Empty input returns []. Do not mutate records. No other keys in results.''',
'service':'''service.py: import validation.normalize, pricing.quote. class Booker(inventory).
book(payload) -> dict {id,sku,quantity,total,status:'active'} if inventory.reserve succeeds, else None.
Validate all fields and calculate price BEFORE touching stock. Calls must be idempotent according to
Inventory.reserve; validation failures raise ValueError and leave stock unchanged. No mutation of payload.
cancel(booking_id) delegates to inventory.release and returns bool. Use supplied inventory, no new DB.
Cross-module APIs: normalize returns id,sku,quantity,unit_price,discount; quote(q,p,d) returns money string;
Inventory.reserve(id,sku,q)->bool; release(id)->bool.'''
},
'ledger':{
'validation':'''validation.py: normalize(data) -> exactly {id,account,amount,currency}.
data must be dict; id/account/currency nonempty strings after strip. Uppercase currency and allow only
USD/EUR/TRY. amount left unchanged for money layer. Ignore unknown keys. Missing keys/type errors raise
ValueError; do not mutate input.''',
'pricing':'''pricing.py: cents(amount) -> int. Accept str/int/float/Decimal excluding bool. Use Decimal(str(value)),
reject nonfinite and zero after rounding. Round to 2 places ROUND_HALF_UP then convert to signed cents.
Invalid values raise ValueError. Examples '1.005'->101, '-1.005'->-101, '0.001' raises ValueError.
format_cents(value) -> signed two-decimal string; value must be int excluding bool; no float precision loss,
including huge integers and negatives. Invalid input raises ValueError.''',
'storage':'''storage.py: class Ledger(path), SQLite persistent storage, thread safe without sharing connections.
post(entry_id,account,amount_cents,currency) -> bool: new posting returns True; duplicate identical tuple
returns False; same id different fields raises ValueError. cents nonzero integer excluding bool; currency
USD/EUR/TRY only; entry_id/account nonempty strings; invalid raises ValueError.
balance(account,currency)->int, default 0. transfer(transfer_id,source,target,amount_cents,currency)->bool:
amount must positive int excluding bool, distinct nonempty accounts. Atomically debit source and credit
target; no overdraft allowed. Insufficient balance raises ValueError and writes nothing. Exact duplicate
transfer returns False; conflicting reuse raises ValueError. Transfer ids and entry ids are separate
namespaces. Persist and handle concurrent transfers without lost updates or overdrafts.''',
'reporting':'''reporting.py: summarize(rows) -> list of dicts sorted by (account,currency), exactly keys
account,currency,balance_cents,entries. Each row has account,currency,amount_cents. Group and sum ints;
entries counts all rows including negative. Empty returns []; do not mutate input. No database dependency.''',
'service':'''service.py: import validation.normalize and pricing.cents. class Accounting(ledger).
post(payload)->bool: normalize, convert amount to cents, then ledger.post(id,account,cents,currency).
Bad money/currency/missing fields must fail before writing. transfer(transfer_id,source,target,amount,currency)
normalizes currency with strip+upper, converts amount to cents and calls ledger.transfer. A negative/zero
transfer raises ValueError. Do not mutate payload. Use injected ledger; return its boolean.'''
},
'queue':{
'validation':'''validation.py: normalize(data)->exactly {id,kind,payload,priority}.
data must be dict. id and kind required nonempty strings after strip. payload defaults to {}, must be dict
which round-trips through JSON without NaN,Infinity or unsupported values; deep copy it so nested mutation
never affects input. priority defaults 0 and must int excluding bool in [-100,100]. All invalid raises
ValueError. Ignore unknown keys.''',
'pricing':'''pricing.py: delay(attempt,base=1,cap=60)->int. attempt integer>=1, base/cap positive integers,
all exclude bool. Return min(cap,base*2**(attempt-1)) without constructing enormous ints (attempt may be
10**9). Invalid raises ValueError. ready_at(now,attempt,base=1,cap=60)-> numeric now+delay(...);
now finite int or float, excluding bool. Invalid now raises ValueError.''',
'storage':'''storage.py: class Queue(path), durable SQLite; safe for multiple instances/threads.
enqueue(job_id,kind,payload,priority=0)->bool: new True, exact duplicate False, same id differing fields
raises ValueError; payload dict JSON data, priority int excluding bool. Validate id/kind nonempty strings.
claim(owner,now,lease_seconds=30)->dict or None: eligible pending job or expired lease, choose priority
descending then id ascending. Atomically set state running, increment attempt; return exactly
{id,kind,payload,priority,attempt,owner,lease_until}. Owner nonempty string, now finite int/float nonbool,
lease_seconds positive finite numeric nonbool. lease_until=now+lease_seconds. Reclaim expired when <=now.
finish(job_id,owner,attempt,now)->bool: set completed only for matching live lease with lease_until>now;
wrong/stale/expired/duplicate returns False. get(job_id)->dict including id,state,attempt, or None if absent.
Completed jobs never claimed. claim concurrency must never return same live job twice. All invalid
enqueue/claim inputs raise ValueError. JSON payload persisted. No process-global in-memory database.''',
'reporting':'''reporting.py: summarize(jobs)->dict with exactly pending,running,completed,total,attempts.
Count each state, total count and sum numeric attempt. Unknown state raises ValueError. Empty returns all
zeros. Do not mutate input. Each input has state and attempt; no database dependency.''',
'service':'''service.py: import validation.normalize. class Worker(queue,owner,handlers).
submit(payload)->bool: normalize and call queue.enqueue(id,kind,payload,priority).
tick(now,lease_seconds=30)->dict or None: claim one job; None if no job. On matching handler success call
queue.finish(id,owner,attempt,now), return {id,status:'completed',result:<handler return>} only if finish
returned True; otherwise {id,status:'stale'}. Handler gets only job['payload']. Unknown handler or exception:
do NOT finish; return {id,status:'failed'}, leaving lease to expire for retry. Do not leak exception text.
Queue.claim returns id,kind,payload,priority,attempt,owner,lease_until. No sleeping/network.'''
}}

PARTS=('validation','pricing','storage','reporting','service')
