# promate-backend

FastAPI gateway + LangGraph agent for **ProMate**, the PartSelect (refrigerator +
dishwasher) chat agent demo.

## Quickstart (local)

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY
uv sync                       # create .venv, install deps
docker compose up -d postgres # Postgres 16 + pgvector
uv run python -m ingestion init-db
uv run python -m ingestion import-catalog   # if catalog empty
uv run uvicorn app.main:app --reload   # http://localhost:8000
```

Health checks:

- `GET /health` — liveness (no deps)
- `GET /api/v1/health` — readiness (includes DB ping)

## Demo conversation scripts

Use these with `POST /api/v1/chat` or the frontend chat widget:

1. **Symptom → part:** `My dishwasher won't drain — what part might I need?`
2. **Compatibility:** `Will PS11752778 fit model WDT780SAEM1?`
3. **Install help:** `How can I install part PS11752778?`
4. **Purchase handoff:** `I'm ready to buy PS11752778` → agent confirms grounded price/stock and links to PartSelect.com
5. **Grounding failure:** `Tell me about part PS99999999` → `I cannot find that part in our catalog`
6. **Order status (mock):** `What is the status of order ORD-DEMO-001?`

## Conversion flow (no cart / no Stripe)

The agent uses tool-first catalog grounding and a conversion state machine:

`SEARCHING → IDENTIFIED → COMPATIBILITY_CONFIRMED → PURCHASE_READY`

Tools: `search_parts`, `get_part_details`, `get_order_status` (mock), `prepare_purchase_handoff`.
Purchase intent in chat advances to `PURCHASE_READY` and emits a `purchase_handoff` SSE event with the PartSelect.com product URL.

## Architecture seam ("scale without rewrites")

| Concern    | Local (`.env` default) | Cloud (config flip)            |
|------------|------------------------|--------------------------------|
| LLM        | Anthropic API          | Same key injected on AgentCore Runtime |
| Embeddings | fastembed (bge-small)  | Bedrock Titan (`EMBEDDINGS_PROVIDER=bedrock`) |
| Database   | Postgres + pgvector    | Aurora Serverless v2 (`DATABASE_URL`) |
| Agent host | uvicorn / FastAPI      | Bedrock AgentCore Runtime      |

## Layout

```
app/
  core/        config, llm, embeddings, db, logging
  api/v1/      chat, parts, health
  agents/      LangGraph graph, tool router, conversion state machine
  tools/       transactional catalog tools
  guardrails/  scope, injection, groundedness
  catalog/     CSV validation, startup checks
```

Tooling: `uv run ruff check .`, `uv run mypy app`, `uv run pytest`, `uv run python -m evals`.
