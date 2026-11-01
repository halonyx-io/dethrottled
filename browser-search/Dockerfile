FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb xauth libegl1 libgles2 \
    && python -m patchright install --with-deps --no-shell chromium \
    && rm -rf /ms-playwright/ffmpeg-* \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10002 browsersearch \
    && chmod -R a+rX /ms-playwright \
    && mkdir /state && chown browsersearch:browsersearch /state

COPY service.py ./
COPY start.sh ./
USER browsersearch
EXPOSE 19888
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19888/health', timeout=3)" || exit 1
CMD ["sh", "/app/start.sh"]
