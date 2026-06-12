# promate-backend

FastAPI gateway + LangGraph agent for **ProMate**, the PartSelect (refrigerator +
dishwasher) chat agent.

## Quickstart (local)

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY (and Stripe keys later)
uv sync                       # create .venv, install deps
docker compose up -d postgres # Postgres 16 + pgvector
uv run uvicorn app.main:app --reload   # http://localhost:8000
```

Or run everything in containers:

```bash
docker compose up --build     # api + postgres
```

Health checks:

- `GET /health` — liveness (no deps)
- `GET /api/v1/health` — readiness (includes DB ping)

## Architecture seam ("scale without rewrites")

Local and cloud differ only by config — the agent graph, tools, and API contract
never change:

| Concern    | Local (`.env` default) | Cloud (config flip)            |
|------------|------------------------|--------------------------------|
| LLM        | Anthropic API          | Same key injected on AgentCore Runtime |
| Embeddings | fastembed (bge-small)  | Bedrock Titan (`EMBEDDINGS_PROVIDER=bedrock`) |
| Database   | Postgres + pgvector    | Aurora Serverless v2 (`DATABASE_URL`) |
| Agent host | uvicorn / FastAPI      | Bedrock AgentCore Runtime      |

## Layout (so far)

```
app/
  core/        config, llm (provider abstraction), embeddings, db, logging
  api/v1/      versioned routers (health; chat/parts/cart land in Phase 3)
  agents/      LangGraph graph + nodes (Phase 2)
  tools/       agent tools (Phase 2)
  guardrails/  scope/injection/groundedness (Phase 2)
  models/      Pydantic + SQLAlchemy models (Phase 1)
```

Tooling: `uv run ruff check .`, `uv run mypy app`, `uv run pytest`.
