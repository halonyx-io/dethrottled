"""Caption and speech evidence with time selectors and explicit uncertainty."""

from __future__ import annotations

import html
import re

from .workers import endpoint


def seconds(value):
    parts = value.replace(",", ".").split(":")
    return sum(float(n) * 60**i for i, n in enumerate(reversed(parts)))


def captions(data, limit):
    source = data.decode("utf-8-sig", "replace").replace("\r\n", "\n")
    segments = []
    for cue in re.split(r"\n\s*\n", source):
        lines = cue.strip().splitlines()
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        marker = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if marker is None:
            continue
        times = lines[marker].split(" --> ", 1)
        try:
            start, end = seconds(times[0]), seconds(times[1].split()[0])
        except (ValueError, IndexError):
            continue
        text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(lines[marker + 1:])))
        if end >= start >= 0 and text.strip():
            segments.append({"start_seconds": start, "end_seconds": end, "text": text.strip()})
        if len(segments) >= 20000:
            break
    if not segments:
        raise ValueError("no_valid_caption_cues")
    return render(segments, limit, method="source_captions")


def render(segments, limit, *, method, language=None, duration=None):
    lines, selected, size = [], [], 0
    for segment in segments:
        line = f"[{segment['start_seconds']:.3f}-{segment['end_seconds']:.3f}] {segment['text']}"
        if size + len(line) + 1 > limit:
            break
        selected.append(segment)
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines), {
        "segments": selected, "total_segments": len(segments),
        "partial": len(selected) < len(segments), "method": method,
        "language": language, "duration_seconds": duration,
        "warnings": ["Speech recognition can hallucinate or mishear; verify important claims "
                     "against source audio. Timings are model estimates."]
        if method == "speech_recognition" else [],
    }


def transcribe(data, limit):
    import requests

    worker = endpoint("speech")
    if not worker:
        raise ValueError("speech_worker_not_configured; provide captions or enable media worker")
    response = requests.post(worker + "/transcribe", data=data,
                             headers={"Content-Type": "application/octet-stream"}, timeout=600)
    if response.status_code != 200:
        raise ValueError("speech_worker_failed:%s" % response.status_code)
    result = response.json()
    return render(result["segments"], limit, method="speech_recognition",
                  language=result.get("language"), duration=result.get("duration_seconds"))
