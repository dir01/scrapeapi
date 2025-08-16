# ScrapeAPI - scrapegraph-ai HTTP API (FastAPI + Docker)

A tiny **FastAPI** service that wraps the open‑source **scrapegraph-ai** graphs so you can call them from **Go** (or anything HTTP), passing **prompt**, **schema**, sources, and runtime options. Includes job-style start/poll endpoints, optional API key auth, and Playwright/Chromium for JS pages.

> Supports: **SmartScraperGraph** (single page), **SmartScraperMultiGraph** (many pages), and **SearchGraph** (web discovery). Schema can be provided as a **Pydantic-like JSON example**, a **JSON Schema object**, or omitted.

## Project Structure

- `app/main.py` - FastAPI service with scraping endpoints
- `Dockerfile` - Container configuration with Playwright/Chromium
- `.env.example` - Environment variables template

---

## Build & Run

```bash
# 1) Build
docker build -t scrapeapi .

# 2) Run (with OpenAI key for example)
docker run -p 8080:8080 \
  -e OPENAI_API_KEY=sk-... \
  scrapeapi
```

Health check:

```bash
curl -s http://localhost:8080/v1/health
```

---

## API

### Start a job (generic)

`POST /v1/scrape`

**Body** (examples below):

```json
{
  "graph": "smart",
  "user_prompt": "Extract the product title and price",
  "website_url": "https://example.com/product/123",
  "schema": {
    "type": "object",
    "properties": {
      "title": {"type": "string"},
      "price": {"type": "string"}
    },
    "required": ["title", "price"]
  },
  "llm": {"model": "openai/gpt-4o-mini", "temperature": 0},
  "headless": true,
  "loader_kwargs": {"proxy": {"server": "http://user:pass@proxy:8080"}},
  "timeout_sec": 120
}
```

**Response**:

```json
{
  "request_id": "uuid",
  "status": "queued",
  "graph": "smart",
  "user_prompt": "...",
  "website_url": "https://example.com/product/123",
  "result": null,
  "error": ""
}
```

### Poll a job

`GET /v1/scrape/{request_id}`

```json
{
  "request_id": "uuid",
  "status": "completed",
  "graph": "smart",
  "user_prompt": "...",
  "result": {
    "data": {"title": "...", "price": "..."},
    "schema_validation": {"ok": true}
  },
  "error": ""
}
```

### Aliases (optional)

* `POST /v1/smartscraper` (same as `/v1/scrape` with `graph=smart`)
* `GET /v1/smartscraper/{request_id}` (poll)

---

## Example Requests

### 1) **Smart** (single page)

```bash
curl -s -X POST http://localhost:8080/v1/scrape \
 -H 'Content-Type: application/json' \
 -d '{
  "graph": "smart",
  "user_prompt": "Extract job: title, company, location, apply_url",
  "website_url": "https://boards.greenhouse.io/example/jobs/123",
  "schema": {
    "type": "object",
    "properties": {
      "title": {"type": "string"},
      "company": {"type": "string"},
      "location": {"type": "string"},
      "apply_url": {"type": "string", "format": "uri"}
    },
    "required": ["title", "apply_url"]
  },
  "llm": {"model": "openai/gpt-4o-mini", "temperature": 0},
  "headless": true
 }'
```

### 2) **Multi** (many pages)

```bash
curl -s -X POST http://localhost:8080/v1/scrape \
 -H 'Content-Type: application/json' \
 -d '{
  "graph": "multi",
  "user_prompt": "For each page, extract a single job with title, company, location, apply_url",
  "sources": [
    "https://boards.greenhouse.io/example/jobs/123",
    "https://jobs.lever.co/example/456"
  ],
  "schema": {"type":"object","properties":{"jobs":{"type":"array","items":{"type":"object","properties":{"title":{"type":"string"},"company":{"type":"string"},"location":{"type":"string"},"apply_url":{"type":"string","format":"uri"}}}}}},
  "llm": {"model": "openai/gpt-4o-mini", "temperature": 0},
  "headless": true,
  "max_results": 20
 }'
```

### 3) **Search** (discovery)

```bash
curl -s -X POST http://localhost:8080/v1/scrape \
 -H 'Content-Type: application/json' \
 -d '{
  "graph": "search",
  "user_prompt": "Find recent postings for Go developer (remote or Tbilisi) and return list of job page URLs",
  "schema": {"type":"object","properties":{"jobs":{"type":"array","items":{"type":"object","properties":{"title":{"type":"string"},"source_url":{"type":"string","format":"uri"}}}}}},
  "llm": {"model": "openai/gpt-4o-mini", "temperature": 0}
 }'
```

---

## Notes & Tips

* **Schema input**: You can pass either a *JSON Schema object* (validated if `jsonschema` is installed) or a *JSON-like example string*. If omitted, scrapegraph-ai decides the shape.
* **Providers**: Set `llm` according to your provider (OpenAI, Anthropic, Mistral, Google, Together, or local **Ollama**). Keys can come from env vars or inline via `llm:{ api_key: ... }`.
* **JS pages**: Enable Chromium by setting `headless: true` and optionally `loader_kwargs.proxy` for geo/rate limits.
* **Raw HTML**: If you can’t hit the URL, send `website_html`; the server writes a temp `.html` file and scrapes that.
* **Persistence**: This demo stores jobs in memory. Swap `JOBS` for Redis/Postgres for production.
* **Timeouts**: Control with `timeout_sec` per request.


