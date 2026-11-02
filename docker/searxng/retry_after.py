"""Preserve upstream Retry-After without shortening SearXNG suspensions.

Kept independent of SearXNG so date parsing and exception behavior can be
tested without starting a search engine or making an upstream request.
"""

import math
import re
import time
from email.utils import parsedate_to_datetime
from functools import wraps


def retry_after_seconds(value, *, now=None):
    """Return nonnegative whole seconds for RFC delay-seconds or HTTP-date."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        try:
            return int(value)
        except ValueError:
            return None
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            return None
        return max(0, math.ceil(deadline.timestamp() - (time.time() if now is None else now)))
    except (ValueError, TypeError, OverflowError):
        return None


def respecting_retry_after(original, refusal_type):
    """Wrap SearXNG's refusal handling, retaining its exception type/policy."""
    if getattr(original, "_dethrottled_retry_after", False):
        return original

    @wraps(original)
    def checked(response):
        try:
            return original(response)
        except refusal_type as exc:
            delay = retry_after_seconds(response.headers.get("Retry-After"))
            if delay is not None and delay > exc.suspended_time:
                exc.suspended_time = delay
                exc.message = f"Upstream refusal; Retry-After honored (suspended_time={delay})"
                exc.args = (exc.message,)
            raise

    checked._dethrottled_retry_after = True
    return checked
