FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS browser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY browser-search/requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb xauth libegl1 libgles2 \
         libgl1-mesa-dri libglx-mesa0 libegl-mesa0 \
    && python -m patchright install --with-deps --no-shell chromium \
    && rm -rf /ms-playwright/ffmpeg-* \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10002 browsersearch \
    && chmod -R a+rX /ms-playwright \
    && mkdir /state && chown browsersearch:browsersearch /state

COPY browser-search/service.py browser-search/recovery.py browser-search/verify_search.py ./
COPY src/dethrottled/licenses/ ./licenses/
COPY src/dethrottled/adblock.py ./dethrottled_adblock.py
COPY src/dethrottled/adblock_browser.py ./dethrottled_adblock_browser.py
COPY src/dethrottled/adblock_proxy.py ./dethrottled_adblock_proxy.py
COPY browser-search/start.sh ./
USER browsersearch
EXPOSE 19888
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19888/health', timeout=3)" || exit 1
CMD ["sh", "/app/start.sh"]

FROM browser AS dnb
USER root
# Crawl4AI imports Playwright's Python API, but DNB launches through Patchright.
# Drop Playwright's unused Node executable in the install layer. Keep its Python
# modules, dependency metadata and third-party notices intact.
RUN pip install --no-cache-dir 'crawl4ai==0.9.5' 'PyJWT[crypto]==2.15.1' -r requirements.txt \
    && python -c 'from pathlib import Path; import playwright; (Path(playwright.__file__).parent / "driver" / "node").unlink()' \
    && pip check && pip freeze > /app/dnb-dependencies.txt
COPY src/dethrottled/delegation.py /app/dethrottled_delegation.py
COPY src/dethrottled/adblock_proxy.py /app/dethrottled_adblock_proxy.py
COPY browser-search/service.py /app/service.py
COPY experiments/dnb/dnb_service.py experiments/dnb/context_pool.py experiments/dnb/network_policy.py experiments/dnb/extraction_pool.py experiments/dnb/extract_worker.py experiments/dnb/html_extract.py experiments/dnb/navigation_guard.py experiments/dnb/lifecycle.py experiments/dnb/session_owners.py experiments/dnb/operation_store.py /app/
COPY experiments/dnb/start.sh /app/dnb-start.sh
USER browsersearch
CMD ["sh", "/app/dnb-start.sh"]

FROM browser AS legacy
