"""The Compose adapter extends upstream suspensions without live searches."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "dethrottled_searxng_retry_after",
    Path(__file__).resolve().parents[1] / "docker/searxng/retry_after.py",
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize("value,expected", [
    ("7200", 7200), (" 120 ", 120), ("0", 0),
    ("Wed, 21 Oct 2015 07:28:00 GMT", 300),
    ("Wed, 21 Oct 2015 07:00:00 GMT", 0),
    (None, None), ("", None), ("later", None),
    ("-1", None), ("1.5", None), ("NaN", None),
])
def test_retry_after(value, expected):
    assert guard.retry_after_seconds(value, now=1445412180) == expected


class Refused(Exception):
    def __init__(self, seconds=180):
        self.suspended_time = seconds
        self.message = "refused"
        super().__init__(self.message)


@pytest.mark.parametrize("header,default,expected", [
    ("7200", 180, 7200), ("60", 3600, 3600),
    ("invalid", 180, 180), (None, 180, 180),
])
def test_refusal_type_and_minimum_suspension_preserved(header, default, expected):
    refusal = Refused(default)

    def original(response):
        raise refusal

    wrapped = guard.respecting_retry_after(original, Refused)
    response = SimpleNamespace(headers={"Retry-After": header})
    with pytest.raises(Refused) as caught:
        wrapped(response)
    assert caught.value is refusal
    assert caught.value.suspended_time == expected
    assert guard.respecting_retry_after(wrapped, Refused) is wrapped
    if expected != default:
        assert str(expected) in str(caught.value)


def test_success_and_other_errors_are_unchanged():
    response = SimpleNamespace(headers={"Retry-After": "7200"})
    assert guard.respecting_retry_after(lambda r: r, Refused)(response) is response

    def failed(response):
        raise ValueError("not a refusal")

    with pytest.raises(ValueError, match="not a refusal"):
        guard.respecting_retry_after(failed, Refused)(response)
