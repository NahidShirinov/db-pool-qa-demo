"""Load test: does a slow external API slow down a page that never calls it?

- Payer: calls the pay endpoint non-stop (each call waits for slow_api.py)
- Browser: opens GET /orders/{id} once a second. Its response time is the measurement.

    ENDPOINT=pay-buggy locust -f locustfile.py --headless -u 30 -r 30 -t 60s --host http://127.0.0.1:8000
    ENDPOINT=pay       locust -f locustfile.py --headless -u 30 -r 30 -t 60s --host http://127.0.0.1:8000
"""

import os

from locust import HttpUser, constant, task

ENDPOINT = os.getenv("ENDPOINT", "pay-buggy")


class _User(HttpUser):
    abstract = True

    def on_start(self) -> None:
        self.order_id = self.client.post("/orders", name="setup").json()["id"]


class Payer(_User):
    fixed_count = int(os.getenv("PAYERS", "25"))
    wait_time = constant(0)

    @task
    def pay(self) -> None:
        self.client.post(f"/orders/{self.order_id}/{ENDPOINT}", name=f"POST /orders/:id/{ENDPOINT} (slow)")


class Browser(_User):
    fixed_count = int(os.getenv("BROWSERS", "5"))
    wait_time = constant(1)

    @task
    def read(self) -> None:
        self.client.get(f"/orders/{self.order_id}", name="GET /orders/:id (unrelated)")
