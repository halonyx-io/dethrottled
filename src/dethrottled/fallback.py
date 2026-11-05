"""Explicitly supported broad-format reads through an optional local Apache Tika worker."""

from pathlib import PurePosixPath

from . import netfilter as requests
from .workers import endpoint

MIMES = {
    ".msg": "application/vnd.ms-outlook",
    ".xlsb": "application/vnd.ms-excel.sheet.binary.macroEnabled.12",
}

def kind(data, name):
    extension = PurePosixPath(name.split("?")[0].lower()).suffix
    if extension == ".msg" and data.startswith(b"\xd0\xcf\x11\xe0"):
        return "msg"
    if extension == ".xlsb" and data.startswith(b"PK"):
        return "xlsb"
    return ""


def read(data, kind, limit):
    worker = endpoint("formats")
    if not worker:
        raise ValueError("format_worker_not_configured:" + kind)
    response = requests.post(
        worker + "/convert",
        params={"mime": MIMES["." + kind]},
        data=data,
        timeout=(5, 65),
        allow_redirects=False,
    )
    if response.status_code != 200:
        raise ValueError("format_worker_failed:" + str(response.status_code))
    result = response.json()
    text = result["text"]
    if not text.strip():
        raise ValueError("format_worker_empty")
    return text[:limit], {
        "parser": result["engine"],
        "parser_version": result["version"],
        "partial": bool(result.get("partial")) or len(text) > limit,
        "warnings": [
            "Fallback parser text; attachment completeness and physical table cells "
            "are not verified."
        ],
        "mime": result["mime"],
    }
