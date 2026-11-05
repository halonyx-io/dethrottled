"""Explicit requests sessions and bounded GET redirects for acquisition clients."""

import os
from urllib.parse import urljoin, urlsplit

import requests as _requests

from . import adblock

RequestException = _requests.RequestException


class Session(_requests.Session):
    def send(self, request, **kwargs):
        target = urlsplit(request.url)
        if (target.scheme, target.netloc) != getattr(self, "_rpc_origin", None):
            adblock.check(request.url, "http")
        return super().send(request, **kwargs)


def request(method, url, **kwargs):
    with Session() as session:
        target = urlsplit(url)
        for variable in (
            "BROWSER_SEARCH",
            "SEARXNG",
            "CRAWL4AI",
            "FORMAT_WORKER",
            "LAYOUT_WORKER",
            "MEDIA_WORKER",
        ):
            configured = os.getenv("DETHROTTLED_" + variable + "_URL", "")
            endpoint = urlsplit(configured)
            if endpoint.netloc and (target.scheme, target.netloc) == (
                endpoint.scheme,
                endpoint.netloc,
            ):
                session._rpc_origin = target.scheme, target.netloc
                break
        return session.request(method, url, **kwargs)


def get(url, **kwargs):
    kwargs.setdefault("allow_redirects", True)
    return request("GET", url, **kwargs)


def post(url, **kwargs):
    return request("POST", url, **kwargs)


def get_using(getter, url, **kwargs):
    """curl_cffi owns TLS; this layer checks before every redirect hop."""
    if not adblock.enabled():
        return getter(url, **kwargs)
    follow = kwargs.pop("allow_redirects", True)
    for _ in range(21):
        adblock.check(url, "tls")
        response = getter(url, **dict(kwargs, allow_redirects=False))
        if not follow or response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        if not location:
            return response
        target = urljoin(url, location)
        if urlsplit(target)[:2] != urlsplit(url)[:2]:
            kwargs = {k: v for k, v in kwargs.items() if k not in {"cookies", "auth"}}
            if kwargs.get("headers"):
                kwargs["headers"] = {
                    k: v
                    for k, v in kwargs["headers"].items()
                    if k.lower() not in {"authorization", "cookie", "proxy-authorization"}
                }
        response.close()
        url = target
    raise ValueError("too_many_redirects")


def install_ddgs():
    """DDGS uses a separate native transport; guard its HTTP boundary explicitly."""
    if not adblock.enabled():
        return
    from ddgs.http_client import HttpClient

    if getattr(HttpClient.request, "_dethrottled_filter", False):
        return
    original = HttpClient.request

    def filtered(self, method, url, *args, **kwargs):
        if not adblock.enabled():
            return original(self, method, url, *args, **kwargs)
        # DDGS discovery methods are GET/POST. Reuse native request for each hop,
        # retaining its original TLS configuration and session cookie store.
        follow = kwargs.pop("follow_redirects", True)
        for _ in range(21):
            adblock.check(url, "ddgs")
            response = original(self, method, url, *args, **dict(kwargs, follow_redirects=False))
            headers = getattr(response, "headers", None) or response._resp.headers
            location = headers.get("location")
            if not follow or response.status_code not in {301, 302, 303, 307, 308} or not location:
                return response
            target = urljoin(url, location)
            if urlsplit(target)[:2] != urlsplit(url)[:2]:
                kwargs.pop("auth", None)
                kwargs.pop("auth_bearer", None)
                kwargs.pop("cookies", None)
                if kwargs.get("headers"):
                    kwargs["headers"] = {
                        k: v
                        for k, v in kwargs["headers"].items()
                        if k.lower() not in {"authorization", "cookie"}
                    }
            if response.status_code == 303 or (
                response.status_code in {301, 302} and method.upper() == "POST"
            ):
                method = "GET"
                for key in ("data", "json", "content", "files"):
                    kwargs.pop(key, None)
            kwargs.pop("params", None)
            url = target
        raise ValueError("too_many_redirects")

    filtered._dethrottled_filter = True
    HttpClient.request = filtered


def __getattr__(name):
    # Preserve requests' public exception/types used by existing callers.
    return getattr(_requests, name)
