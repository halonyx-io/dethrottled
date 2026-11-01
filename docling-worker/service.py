"""Private bytes-only layout worker. It never accepts a URL or an API key."""
import asyncio
import json
import subprocess
import sys
import tempfile
import threading

from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
lock = threading.Lock()
LIMIT = 50 * 1024 * 1024


@app.get("/health")
def health():
    return {"status": "ok", "engine": "docling", "version": "2.145.0",
            "mode": "native_text_layout_tables", "ocr": False}


@app.post("/convert")
async def convert(request: Request, page_start: int = 1, page_end: int = 10):
    if page_start < 1 or page_end < page_start or page_end - page_start >= 100:
        raise HTTPException(422, "invalid_page_range")
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "layout_worker_busy")
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as source:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > LIMIT:
                    raise HTTPException(413, "layout_input_limit")
                source.write(chunk)
            source.flush()
            def run():
                try:
                    done = subprocess.run([sys.executable, "convert.py", source.name,
                        json.dumps({"page_start": page_start, "page_end": page_end})],
                        capture_output=True, timeout=180)
                except subprocess.TimeoutExpired:
                    raise HTTPException(504, "layout_timeout") from None
                if done.returncode:
                    # Document text and model logs are never exposed as error messages.
                    raise HTTPException(422, "layout_conversion_failed")
                if len(done.stdout) > 20_000_000:
                    raise HTTPException(413, "layout_output_limit")
                return json.loads(done.stdout)
            task = asyncio.create_task(asyncio.to_thread(run))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Keep the tempfile and single-flight lock until the bounded child exits.
                try:
                    await task
                finally:
                    raise
    finally:
        lock.release()
