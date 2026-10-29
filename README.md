# db-pool-qa-demo

A minimal reproduction of a common performance bug, and how to test for it as QA:
**a database connection held while waiting for a slow external API.**

When the external API gets slow, every request waiting on it keeps a connection from the pool. Once the pool (15 connections by default in SQLAlchemy) is empty, pages that never call that API have to wait too.

This is not a real backend. It is one small FastAPI file with two versions of the same endpoint, so the bug and the fix can be compared side by side.

| File | What it is |
|---|---|
| `app.py` | `POST /orders/{id}/pay-buggy` (bug), `POST /orders/{id}/pay` (fix), `GET /orders/{id}` (unrelated page) |
| `tests/test_connection_release.py` | Regression test: no connection may be checked out while the external API answers |
| `slow_api.py` | Fake external payment API that answers after N seconds |
| `locustfile.py` | Load test: 25 users paying, 5 users opening an unrelated page |

## The bug and the fix

```python
# bug: the connection stays checked out during the external call
order = load(db, order_id)
order.status = charge(order.total)   # waits for the external API
db.commit()

# fix: give the connection back before the slow call
order = load(db, order_id)
amount = order.total
db.commit()
status = charge(amount)
order.status = status
db.commit()
```

## Run the regression test

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -v
```

The test replaces the external API with a fake that records `engine.pool.checkedout()` at the moment the request arrives. The fixed endpoint must show `0`. A second test runs the buggy endpoint and expects `1`, which proves the check can actually fail.

## Run the load test

Three terminals:

```bash
.venv/bin/python slow_api.py 9100 5             # external API answers in 5 s
.venv/bin/uvicorn app:app --port 8000
pip install locust
ENDPOINT=pay-buggy locust -f locustfile.py --headless -u 30 -r 30 -t 60s --host http://127.0.0.1:8000
ENDPOINT=pay       locust -f locustfile.py --headless -u 30 -r 30 -t 60s --host http://127.0.0.1:8000
```

Look at `GET /orders/:id (unrelated)`. That page never calls the external API.

Example run on a laptop (SQLite, one uvicorn process, 60 s each):

| | `pay-buggy` | `pay` |
|---|---|---|
| Unrelated page, median | 4,000 ms | 7 ms |
| Unrelated page, slowest | 9,002 ms | 23 ms |
| Pay requests completed | 165 | 275 |
| Pay request, median (API takes 5 s) | 10,000 ms | 5,006 ms |

Your numbers will differ. The gap between the two columns is the point.

## Where to look in a real system

Any network call between the first database query and the commit: payments, webhooks, email/SMS, file uploads, LLM calls, and background jobs that keep one session for the whole job.
