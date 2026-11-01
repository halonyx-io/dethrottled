"""Private broad-format fallback. Caller URLs never enter this worker."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from runtime import Runner

app = FastAPI()
runner = Runner("convert.py", timeout=60)


@app.get("/health")
@app.get("/ready")
def health():
    if not Path("/opt/tika.jar").is_file():
        raise HTTPException(503, "tika_jar_missing")
    return {"status": "ok", "engine": "apache-tika", "version": "3.3.3"}


@app.get("/metrics")
def metrics():
    return runner.metrics()


@app.post("/convert")
async def convert(request: Request, mime: str):
    return await runner.execute(request, {"mime": mime})
