# Build browser-search/Dockerfile as dethrottled-dnb-browser:reference first.
# Tests pass the frozen 1.7.1 image ID instead; never mutate production tags.
ARG BROWSER_IMAGE=dethrottled-dnb-browser:reference
FROM ${BROWSER_IMAGE}
USER root
# Retain upstream extraction implementation, but install no second browser.
RUN pip install --no-cache-dir 'crawl4ai==0.9.5' 'patchright==1.63.0' \
    'fastapi==0.142.2' 'uvicorn==0.54.0' \
    && pip check && pip freeze > /app/dnb-dependencies.txt
RUN pip install --no-cache-dir 'PyJWT[crypto]==2.15.1' \
    && pip check && pip freeze > /app/dnb-dependencies.txt
COPY src/dethrottled/delegation.py /app/dethrottled_delegation.py
COPY src/dethrottled/adblock_proxy.py /app/dethrottled_adblock_proxy.py
COPY browser-search/service.py /app/service.py
COPY experiments/dnb/dnb_service.py experiments/dnb/context_pool.py experiments/dnb/network_policy.py experiments/dnb/extraction_pool.py experiments/dnb/extract_worker.py experiments/dnb/html_extract.py experiments/dnb/navigation_guard.py experiments/dnb/lifecycle.py experiments/dnb/session_owners.py experiments/dnb/operation_store.py /app/
COPY experiments/dnb/start.sh /app/dnb-start.sh
USER browsersearch
CMD ["sh", "/app/dnb-start.sh"]
