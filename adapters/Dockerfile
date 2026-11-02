FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
WORKDIR /app
COPY requirements/adapters.lock ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10004 adapter \
    && mkdir /state && chown adapter:adapter /state
COPY src/dethrottled/access.py ./dethrottled_access.py
COPY src/dethrottled/workflow.py ./dethrottled_workflow.py
COPY src/dethrottled/__init__.py ./dethrottled_version.py
COPY scripts/verify_adapter.py ./verify_adapter.py
COPY adapters/mcp_server.py ./server.py
COPY adapters/rest_gateway.py ./public_gateway.py
USER adapter
ENV DETHROTTLED_ADMISSION_DB=/state/admission.sqlite \
    DETHROTTLED_TOKEN_REGISTRY=/run/secrets/tokens.json
EXPOSE 18184 18186
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "18184"]
