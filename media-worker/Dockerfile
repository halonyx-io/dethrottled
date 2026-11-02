FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.121.3 uvicorn==0.38.0 faster-whisper==1.2.1 \
    && useradd --create-home --uid 10003 mediaworker \
    && mkdir /models && chown mediaworker:mediaworker /models
COPY media-worker/service.py media-worker/transcribe.py ./
COPY workers/runtime.py ./
USER mediaworker
ENV WHISPER_MODEL=small
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19889/health',timeout=3)"
EXPOSE 19889
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "19889"]
