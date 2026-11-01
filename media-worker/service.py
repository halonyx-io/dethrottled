"""Private bytes-only transcription with killable deadlines and disconnect recovery."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from runtime import Runner

app = FastAPI()
runner = Runner("transcribe.py", timeout=int(os.getenv("MEDIA_WORKER_DEADLINE", "570")))


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": os.getenv("WHISPER_MODEL", "small"),
        "supervision": "killable_child",
        "model_cached": any(Path("/models").rglob("model.bin")),
    }


@app.get("/ready")
def ready():
    from fastapi import HTTPException

    result = health()
    if not result["model_cached"]:
        raise HTTPException(503, "speech_model_not_cached; first transcription downloads weights")
    return result


@app.get("/metrics")
def metrics():
    return runner.metrics()


@app.post("/transcribe")
async def read(request: Request):
    return await runner.execute(request)
