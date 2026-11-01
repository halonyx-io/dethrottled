"""Private bytes-only layout/OCR worker with killable deadlines."""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from runtime import Runner

app = FastAPI()
runner = Runner("convert.py", timeout=180, suffix=".pdf")


@app.get("/health")
def health():
    return {"status": "ok", "engine": "docling", "version": "2.145.0",
            "mode": "layout_tables_ocr", "ocr": "tesseract_cli"}


@app.get("/ready")
def ready():
    if not any(Path("/models").rglob("*.safetensors")):
        raise HTTPException(503, "layout_models_not_cached; first conversion downloads weights")
    return health()


@app.get("/metrics")
def metrics():
    return runner.metrics()


@app.post("/convert")
async def convert(request: Request, page_start: int = 1, page_end: int = 10,
                  ocr: bool = True, ocr_language: str = "eng"):
    if page_start < 1 or page_end < page_start or page_end - page_start >= 100:
        raise HTTPException(422, "invalid_page_range")
    if ocr_language not in {"eng", "msa", "chi_sim", "chi_tra"}:
        raise HTTPException(422, "unsupported_ocr_language")
    return await runner.execute(request, {"page_start": page_start, "page_end": page_end,
                                          "ocr": ocr, "ocr_language": ocr_language})
