# tests/stress/locustfile.py
"""
Locust load test for the Peluqueria booking bot.
Run from project root: locust -f tests/stress/locustfile.py --host http://localhost:8000

BookingUser (weight=70): simulates a client completing the full 6-step booking flow.
MenuUser (weight=30): simulates a client that just sends "hola" (menu-only traffic).
"""
from uuid import uuid4

from locust import HttpUser, between, task

from tests.stress.payloads import (
    step_enter_name,
    step_hola,
    step_menu_book,
    step_select_day,
    step_select_hour,
    step_service_corte,
)

_HEADERS = {"Content-Type": "application/json"}


class BookingUser(HttpUser):
    """Simulates a client progressing through the full booking conversation."""

    weight = 70
    wait_time = between(0.3, 0.8)

    def on_start(self):
        self._new_session()

    def _new_session(self):
        self.phone = "346" + str(uuid4().int)[:9]
        self._steps = [
            step_hola,
            step_menu_book,
            step_service_corte,
            step_select_day,
            step_select_hour,
            step_enter_name,
        ]
        self.step_idx = 0

    @task
    def do_step(self):
        step_fn = self._steps[self.step_idx]
        payload = step_fn(self.phone)
        self.client.post("/webhook", json=payload, headers=_HEADERS)
        self.step_idx += 1
        if self.step_idx >= len(self._steps):
            # Start fresh with a new phone number
            self._new_session()


class MenuUser(HttpUser):
    """Simulates clients that send a greeting and never proceed further."""

    weight = 30
    wait_time = between(0.3, 0.8)

    @task
    def just_menu(self):
        phone = "346" + str(uuid4().int)[:9]
        payload = step_hola(phone)
        self.client.post("/webhook", json=payload, headers=_HEADERS)
