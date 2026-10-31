"""Private bytes-only CPU transcription worker; it never resolves caller URLs."""

import asyncio
import io
import os
import threading

import av
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from faster_whisper import WhisperModel

app = FastAPI()
lock = threading.Lock()
model = None


@app.get("/health")
def health():
    return {"status": "ok", "model": os.getenv("WHISPER_MODEL", "small"),
            "loaded": model is not None}


def transcribe(data):
    global model
    # Decode incrementally, enforcing duration before allocating an unbounded waveform.
    samples, count = [], 0
    ceiling = int(os.getenv("MEDIA_MAX_SECONDS", "1800")) * 16000
    with av.open(io.BytesIO(data)) as container:
        if not container.streams.audio:
            raise ValueError("no_audio_stream")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for audio in resampler.resample(frame):
                chunk = audio.to_ndarray().flatten()
                count += chunk.size
                if count > ceiling:
                    raise ValueError("media_duration_limit")
                samples.append(chunk)
    if not samples:
        raise ValueError("no_audio_stream")
    waveform = np.concatenate(samples).astype(np.float32) / 32768
    with lock:
        if model is None:
            model = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="cpu",
                                 compute_type="int8", download_root="/models")
        segments, info = model.transcribe(waveform, beam_size=5, vad_filter=True)
        result = [{"start_seconds": s.start, "end_seconds": s.end, "text": s.text.strip()}
                  for s in segments if s.text.strip()]
    return {"segments": result, "language": info.language,
            "duration_seconds": len(waveform) / 16000}


gate = asyncio.Semaphore(1)


@app.post("/transcribe")
async def read(request: Request):
    if gate.locked():
        raise HTTPException(429, "media_worker_busy")
    async with gate:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 50 * 1024 * 1024:
                raise HTTPException(413, "media_byte_limit")
        try:
            return await asyncio.to_thread(transcribe, bytes(data))
        except (ValueError, av.error.FFmpegError) as exc:
            raise HTTPException(422, str(exc)[:100]) from exc
