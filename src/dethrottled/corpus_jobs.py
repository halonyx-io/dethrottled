"""Cooperative inference admission: waiting live queries precede index batches."""

import threading
from contextlib import contextmanager

_CONDITION = threading.Condition()
_BUSY = False
_WAITING = 0


@contextmanager
def inference(*, background=False):
    global _BUSY, _WAITING
    with _CONDITION:
        if not background:
            _WAITING += 1
        try:
            while _BUSY or (background and _WAITING):
                _CONDITION.wait()
            _BUSY = True
        finally:
            if not background:
                _WAITING -= 1
    try:
        yield
    finally:
        with _CONDITION:
            _BUSY = False
            _CONDITION.notify_all()
