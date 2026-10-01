# pdf-worker

HTML in, PDF out, using the Chromium that is already in the `crawl4ai` image.

Why: crawl4ai's own `/pdf` endpoint takes only a URL and prints with Playwright's defaults (Letter paper, CSS `@page`
rules ignored), which loses A4 and running page footers. This prints with the CSS page size honoured.

It renders only the HTML it is handed: the browser context is offline with JavaScript off, so nothing in the HTML can
fetch anything, which is why it is safe to leave open to a trusted LAN. The browser is started per request and closed
after it; one render at a time; `init: true` in the Compose file so no Chromium helper is left as a zombie.

    POST /pdf   {"html": "<!doctype html>...", "format": "A4"}   ->  application/pdf
    GET  /health

Enable it by adding `docker-compose.pdf-worker.yml` to `COMPOSE_FILE` in `.env`, for example
`COMPOSE_FILE=docker-compose.yml:docker-compose.pdf-worker.yml:docker-compose.override.yml`.
The image is the same one `crawl4ai` uses in `docker-compose.yml`; keep the two pins in step.
