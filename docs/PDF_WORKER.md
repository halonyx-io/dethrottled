# Optional HTML-to-PDF worker

This is a separate service that prints HTML you supply to a PDF. It uses the
Chromium already present in the pinned Crawl4AI image; it is not a route on
the Dethrottled API. The worker starts a browser for each request, prints with
CSS page size honored, and closes the browser afterward. Its browser context
has JavaScript disabled and is offline; it cannot fetch referenced network
resources while rendering.

Enable the overlay in `.env`:

```env
COMPOSE_FILE=docker-compose.yml:docker-compose.pdf-worker.yml
```

Then start or recreate the stack:

```sh
docker compose up -d
curl http://127.0.0.1:8788/health
```

The current overlay publishes `8788` on all host interfaces. Change the port
mapping if your deployment needs a narrower bind. This is configuration, not
a firewall rule.

Print an HTML file with a small Python example:

```python
import json
from pathlib import Path
from urllib.request import Request, urlopen

payload = json.dumps({
    "html": Path("report.html").read_text(encoding="utf-8"),
    "format": "A4",
}).encode()
request = Request(
    "http://127.0.0.1:8788/pdf",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=120) as response:
    Path("report.pdf").write_bytes(response.read())
```

Supported `format` values are `A4`, `A3`, `Letter`, and `Legal`; the default
is `A4`. `POST /pdf` returns `application/pdf`. Requests larger than 20 MB
receive 413. The worker renders one request at a time; an overfull wait can
return 503. `GET /health` checks its process. Keep the PDF worker image pin in
step with Crawl4AI's pin in `docker-compose.yml` when upgrading.
