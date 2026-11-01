FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 tesseract-ocr tesseract-ocr-msa tesseract-ocr-chi-sim tesseract-ocr-chi-tra && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir docling==2.145.0 fastapi==0.121.3 uvicorn==0.38.0 \
    && useradd --create-home --uid 10004 docworker && mkdir /models && chown docworker:docworker /models
COPY docling-worker/service.py docling-worker/convert.py ./
COPY workers/runtime.py ./
USER docworker
ENV HF_HOME=/models OMP_NUM_THREADS=4
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19891/health',timeout=3)"
EXPOSE 19891
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "19891"]
