FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb xauth \
    && python -m patchright install --with-deps --no-shell chromium \
    && rm -rf /ms-playwright/ffmpeg-* \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10002 browsersearch \
    && chmod -R a+rX /ms-playwright

COPY service.py ./
USER browsersearch
EXPOSE 19888
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19888/health', timeout=3)" || exit 1
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/tmp/xvfb.log 2>&1 & export DISPLAY=:99; sleep 1; exec uvicorn service:app --host 0.0.0.0 --port 19888"]
