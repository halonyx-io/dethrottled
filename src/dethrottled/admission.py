"""Bounded round-robin admission for expensive local work; no hourly quota."""

import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager


class AdmissionError(RuntimeError):
    pass


class FairQueue:
    def __init__(self, capacity=2, max_waiting=32, per_client=8):
        if min(capacity, max_waiting, per_client) < 1:
            raise ValueError("admission limits must be positive")
        self.capacity, self.max_waiting, self.per_client = capacity, max_waiting, per_client
        self.condition = threading.Condition()
        self.clients = OrderedDict()
        self.active = 0
        self.counts = dict(started=0, completed=0, rejected=0, timed_out=0)

    @contextmanager
    def slot(self, client="local", timeout=60):
        ticket = object()
        started = time.monotonic()
        with self.condition:
            waiting = sum(map(len, self.clients.values()))
            if waiting >= self.max_waiting or len(self.clients.get(client, [])) >= self.per_client:
                self.counts["rejected"] += 1
                raise AdmissionError("renderer_queue_full")
            self.clients.setdefault(client, deque()).append(ticket)
            while True:
                first = next(iter(self.clients))
                if (
                    first == client
                    and self.clients[first][0] is ticket
                    and self.active < self.capacity
                ):
                    queue = self.clients.pop(first)
                    queue.popleft()
                    if queue:
                        self.clients[first] = queue
                    self.active += 1
                    self.counts["started"] += 1
                    self.condition.notify_all()
                    break
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    queue = self.clients[client]
                    queue.remove(ticket)
                    if not queue:
                        del self.clients[client]
                    self.counts["timed_out"] += 1
                    self.condition.notify_all()
                    raise AdmissionError("renderer_queue_timeout")
                self.condition.wait(remaining)
        try:
            yield int((time.monotonic() - started) * 1000)
        finally:
            with self.condition:
                self.active -= 1
                self.counts["completed"] += 1
                self.condition.notify_all()

    def stats(self):
        with self.condition:
            return {
                **self.counts,
                "active": self.active,
                "waiting": sum(map(len, self.clients.values())),
                "clients_waiting": len(self.clients),
                "capacity": self.capacity,
                "max_waiting": self.max_waiting,
                "per_client_waiting": self.per_client,
            }
