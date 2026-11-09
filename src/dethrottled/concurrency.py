"""Carry request-local verified identity through bounded thread-pool work."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context


class ContextExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        return super().submit(copy_context().run, fn, *args, **kwargs)
