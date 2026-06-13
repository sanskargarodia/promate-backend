# promate-backend

FastAPI gateway + LangGraph agent for **ProMate**, the PartSelect (refrigerator and dishwasher) chat agent demo.

**You do not need to run this backend repo to use ProMate.** The full application is hosted on AWS using Bedrock AgentCore and ECR. Simply open [promate-agent.vercel.app](https://promate-agent.vercel.app) and the frontend will route requests to the cloud backend. The first call after idle may take a little time while AgentCore activates the agent in the runtime.

## Quickstart (local)

Only needed if you are developing or debugging the backend itself.

**Turn on Docker Desktop** before starting Postgres (the `pgvector/pgvector:pg16` image).

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY
uv sync                       # create .venv, install deps
docker compose up -d          # Postgres 16 + pgvector (requires Docker Desktop)
uv run python -m ingestion init-db
uv run python -m ingestion import-catalog   # if catalog empty
uv run uvicorn app.main:app --reload   # http://localhost:8000
```

To run only Postgres while developing against a local uvicorn process:

```bash
docker compose up -d postgres
```

**AgentCore Runtime (same graph, port 8080):**

```bash
uv run python -m app.agent_core_entrypoint
# POST http://127.0.0.1:8080/invocations  {"prompt": "..."}
# Streams text/event-stream SSE chunks matching /api/v1/chat event payloads
```

Health checks:

- `GET /health`: liveness (no deps)
- `GET /api/v1/health`: readiness (includes DB ping)

## Demo conversation scripts

Use these with `POST /api/v1/chat` or the frontend chat assistant:

1. **Symptom → part:** `My dishwasher won't drain. What part might I need?`
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

| Concern    | Local (`.env` default) | Cloud (config flip)                           |
| ---------- | ---------------------- | --------------------------------------------- |
| LLM        | Anthropic API          | Same key injected on AgentCore Runtime        |
| Embeddings | fastembed (bge-small)  | Bedrock Titan (`EMBEDDINGS_PROVIDER=bedrock`) |
| Database   | Postgres + pgvector    | Aurora Serverless v2 (`DATABASE_URL`)         |
| Agent host | uvicorn / FastAPI      | Bedrock AgentCore Runtime                     |

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

Tooling: `uv run ruff check .`, `uv run mypy app`, `uv run pytest`.

Evals:

- `uv run python -m evals`: smoke (routing + guardrails, no API key)
- `uv run python -m evals trajectory`: full dataset routing trajectory
- `uv run python -m evals trajectory --graph`: + DB graph tool execution
- `uv run python -m evals live --canonical`: live E2E (API key + DB)

## Deploy to AWS (AgentCore Runtime)

See **[deploy/README.md](deploy/README.md)** for Aurora setup, `agentcore configure` /
`agentcore deploy`, and smoke-test scripts.
