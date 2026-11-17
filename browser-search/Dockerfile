FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS browser

# auto: Google Chrome on amd64, Chromium elsewhere. chromium: Chromium anywhere
# (for example to redistribute the image; see THIRD-PARTY-NOTICES.md).
ARG DNB_BROWSER=auto
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY browser-search/requirements.txt ./
# Google Chrome on amd64: it read Google search 8 times in 8 where Chromium got
# 1 in 15, with the same accuracy and latency elsewhere (web-bench
# browser-settings-ab, rounds 3-4). Chromium on arm64, where Patchright installs
# no Chrome build. One browser per image: Chrome is 452 MB, Chromium 393 MB.
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb xauth libegl1 libgles2 \
         libgl1-mesa-dri libglx-mesa0 libegl-mesa0 \
    && if [ "$DNB_BROWSER" != "chromium" ] && [ "$(dpkg --print-architecture)" = "amd64" ]; then \
         python -m patchright install --with-deps chrome; \
       else \
         python -m patchright install --with-deps --no-shell chromium; \
       fi \
    && rm -rf /ms-playwright/ffmpeg-* \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10002 browsersearch \
    && mkdir -p /ms-playwright && chmod -R a+rX /ms-playwright \
    && mkdir /state && chown browsersearch:browsersearch /state \
    && for d in /etc/opt/chrome/policies/managed /etc/chromium/policies/managed \
                /etc/opt/chrome_for_testing/policies/managed; do mkdir -p "$d"; done
# Secure DNS off: the worker's DNS filter must be the only resolver Chrome uses
# (adblock and public-only addressing on the native lane; see browser_guard).
COPY browser-search/chrome-policy.json /etc/opt/chrome/policies/managed/dethrottled.json
COPY browser-search/chrome-policy.json /etc/chromium/policies/managed/dethrottled.json
COPY browser-search/chrome-policy.json /etc/opt/chrome_for_testing/policies/managed/dethrottled.json

COPY browser-search/service.py browser-search/recovery.py browser-search/verify_search.py ./
COPY src/dethrottled/licenses/ ./licenses/
COPY src/dethrottled/adblock.py ./dethrottled_adblock.py
COPY src/dethrottled/adblock_browser.py ./dethrottled_adblock_browser.py
COPY src/dethrottled/adblock_proxy.py ./dethrottled_adblock_proxy.py
COPY src/dethrottled/browser_guard.py ./dethrottled_browser_guard.py
EXPOSE 19888

FROM browser AS dnb
# nftables for the egress firewall; one UID per browser identity plus the DNS
# filter, and a group shared with the worker for download artifacts.
RUN pip install --no-cache-dir 'PyJWT[crypto]==2.15.1' -r requirements.txt \
    && pip check && pip freeze > /app/dnb-dependencies.txt \
    && apt-get update && apt-get install -y --no-install-recommends nftables \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10010 dnb-shared \
    && useradd --uid 10003 --no-create-home --shell /usr/sbin/nologin dnb-dns \
    && useradd --uid 10005 --create-home --home-dir /home/dnb-public --shell /usr/sbin/nologin dnb-public \
    && useradd --uid 10006 --create-home --home-dir /home/dnb-scoped --shell /usr/sbin/nologin dnb-scoped
COPY src/dethrottled/delegation.py /app/dethrottled_delegation.py
COPY src/dethrottled/dns_filter.py /app/dethrottled_dns_filter.py
COPY src/dethrottled/egress_firewall.py /app/dethrottled_egress_firewall.py
COPY experiments/dnb/dnb_service.py experiments/dnb/context_pool.py experiments/dnb/network_policy.py experiments/dnb/navigation_guard.py experiments/dnb/lifecycle.py experiments/dnb/session_owners.py experiments/dnb/operation_store.py /app/
COPY experiments/dnb/start.sh /app/dnb-start.sh
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19888/health', timeout=3)" || exit 1
# Starts as root only to load the egress firewall (NET_ADMIN), start the DNS
# filter and one unprivileged browser server per identity; everything then runs
# without capabilities (dnb-start.sh).
CMD ["sh", "/app/dnb-start.sh"]
