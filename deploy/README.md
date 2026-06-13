# Deploy ProMate to Amazon Bedrock AgentCore Runtime

This guide deploys **`app/agent_core_entrypoint.py`** — the same LangGraph agent as
`POST /api/v1/chat`, hosted on AgentCore Runtime (port **8080**, streaming SSE).

FastAPI (`app/main.py`) stays the local/parts-API host; only the agent moves to AgentCore.

**You do not need a Dockerfile.** The starter toolkit’s default **direct code deploy**
packages your Python entrypoint + `requirements.txt` into a zip, uploads to S3, and
runs it serverlessly. If you later switch to **container** deploy, `agentcore configure`
generates the Dockerfile for you.

## Architecture

```text
Aurora PostgreSQL (pgvector + catalog + LangGraph checkpoints)
        ↑
AgentCore Runtime  ←  app/agent_core_entrypoint.py  (this deploy)
        ↑
InvokeAgentRuntime (boto3 / agentcore invoke)
        ↑
Frontend or thin proxy (future)
```

## Prerequisites

| Requirement        | Notes                                                                                                                         |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| AWS account + CLI  | `aws sts get-caller-identity`                                                                                                 |
| IAM permissions    | [Starter toolkit permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-toolkit.html) |
| **Cloud Postgres** | Aurora Serverless v2 or RDS with **pgvector** — not `localhost`                                                               |
| Anthropic API key  | Injected as runtime env var (agent calls Anthropic directly)                                                                  |
| Python 3.11+       | Same as local dev                                                                                                             |

Install the deploy CLI (one-time):

```powershell
cd promate-backend
uv pip install bedrock-agentcore-starter-toolkit
agentcore --help
```

## Step 0 — Prepare cloud database

From your machine (with network access to Aurora):

```powershell
cd promate-backend
$env:DATABASE_URL = "postgresql+psycopg://USER:PASS@your-aurora-host:5432/promate"
$env:DATABASE_URL_SYNC = "postgresql://USER:PASS@your-aurora-host:5432/promate"
uv run python -m ingestion init-db
uv run python -m ingestion import-catalog
```

Ensure the AgentCore runtime security group can reach Aurora on port **5432**.

**Cloud embedding swap (recommended):** set `EMBEDDINGS_PROVIDER=bedrock` and
`EMBEDDING_DIM=1024` at deploy time. Your Aurora vectors must match (re-embed if you
started locally with fastembed/384-dim).

## Step 1 — Export requirements

Regenerate after dependency changes:

```powershell
.\deploy\export-requirements.ps1
```

`requirements.txt` is a runtime-only export (Playwright/scrape deps pruned). Local dev
still uses `uv sync` from `pyproject.toml`.

## Step 2 — Configure the agent

Copy and fill environment template:

```powershell
Copy-Item deploy\env.agentcore.example deploy\env.agentcore.local
# Edit deploy\env.agentcore.local — never commit secrets
```

Configure for **direct code deploy** (default — no Docker):

```powershell
agentcore configure `
  -e app/agent_core_entrypoint.py `
  -r us-east-1 `
  --deployment-type direct_code_deploy `
  --requirements-file requirements.txt `
  --runtime PYTHON_3_11 `
  --disable-memory `
  --non-interactive
```

Configuration is stored in **`.bedrock_agentcore.yaml`** (created by configure).

We use **`--disable-memory`** because multi-turn state lives in the **LangGraph Postgres
checkpointer**, not AgentCore Memory.

## Step 3 — Deploy

**Manual (local):**

```powershell
# PowerShell — always pass runtime env vars; bare `agentcore deploy` wipes them.
$env:AGENTCORE_SUPPRESS_RECOMMENDATION = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:NO_COLOR = "1"
Copy-Item deploy\bedrock_agentcore.yaml .bedrock_agentcore.yaml
$envArgs = @()
Get-Content deploy\env.agentcore.local | ForEach-Object {
  $line = $_.Trim()
  if ($line -and -not $line.StartsWith('#') -and $line -match '^([^=]+)=(.*)$') {
    $envArgs += "--env"; $envArgs += ($matches[1] + '=' + $matches[2])
  }
}
agentcore deploy @envArgs
```

**Linux / CI:**

```bash
# Export env from deploy/env.agentcore.local, then:
bash deploy/deploy-agentcore.sh
```

**GitHub Actions (automatic on push):**

Workflow: `.github/workflows/deploy-agentcore.yml`

Triggers on push to `feature/agentcore-runtime` or `main` when agent/runtime files change.
Runs CodeBuild container deploy + smoke test.

Add these **repository secrets** (Settings → Secrets and variables → Actions):

| Secret                  | Description                                                   |
| ----------------------- | ------------------------------------------------------------- |
| `AWS_ACCESS_KEY_ID`     | IAM user/role with AgentCore deploy + CodeBuild permissions   |
| `AWS_SECRET_ACCESS_KEY` | Matching secret key                                           |
| `ANTHROPIC_API_KEY`     | Agent LLM API key                                             |
| `DATABASE_URL`          | Aurora async URL (`postgresql+psycopg://...?sslmode=require`) |
| `DATABASE_URL_SYNC`     | Aurora sync URL for LangGraph checkpointer                    |

Non-secret runtime defaults (region, embeddings, log level) are set in the workflow file.

**IAM for GitHub Actions:** use a deploy-capable IAM user, not an invoke-only user.
`promate-vercel-invoker` is scoped for Vercel → `InvokeAgentRuntime` and will fail on
`codebuild:CreateProject` during deploy. Either:

1. **Recommended:** create `promate-agentcore-deployer` with the policy in
   `deploy/github-actions-iam-policy.json`, and put _that_ user's keys in GitHub secrets.
2. **Alternative:** attach the same policy to your existing deploy user (the one that
   succeeds with local `agentcore deploy`).

Apply in IAM → Users → _user_ → Add permissions → Create inline policy → JSON → paste
from `deploy/github-actions-iam-policy.json`.

Or inline (one-off):

```powershell
agentcore deploy `
  --env ANTHROPIC_API_KEY=sk-ant-... `
  --env DATABASE_URL=postgresql+psycopg://...@aurora:5432/promate `
  --env DATABASE_URL_SYNC=postgresql://...@aurora:5432/promate `
  --env AWS_REGION=us-east-1 `
  --env EMBEDDINGS_PROVIDER=bedrock `
  --env EMBEDDING_DIM=1024 `
  --env APP_ENV=production
```

Check status:

```powershell
agentcore status
```

Save the **agent runtime ARN** from deploy output (also under `bedrock_agentcore:` in
`.bedrock_agentcore.yaml`).

## Step 4 — Smoke test

**CLI:**

```powershell
agentcore invoke '{"prompt": "Will PS11752778 fit model WDT780SAEM1?"}'
```

**boto3 script (included):**

```powershell
$env:AGENT_RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:ACCOUNT:runtime/..."
$env:AWS_REGION = "us-east-1"
uv run python deploy/invoke_agent.py "I'm ready to buy PS11752778"
```

Expected: streamed `data: {"type":"session",...}` SSE chunks, then `token`,
`product_card`, and `done` — same shape as FastAPI `/api/v1/chat`.

## Step 5 — Local smoke test (optional)

Run the entrypoint locally before pushing to AWS:

```powershell
uv run python -m app.agent_core_entrypoint
curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" -d "{\"prompt\": \"Hello\"}"
```

## Step 6 — Wire the frontend (not included)

The Next.js widget today calls `POST /api/v1/chat` on FastAPI. For AgentCore you
need a thin proxy that:

1. Accepts the same chat request body
2. Calls `InvokeAgentRuntime` with `runtimeSessionId` = `thread_id`
3. Forwards SSE chunks to the browser

Keep FastAPI for `/api/v1/parts` browse APIs, or migrate those separately.

## Observability

Enable [AgentCore observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability.html)
(CloudWatch Transaction Search) before deploy for traces and logs:

- Log group: `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT`

## Troubleshooting

| Symptom                          | Fix                                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Catalog not ready                | Run `import-catalog` against Aurora; check `DATABASE_URL` env on runtime                               |
| Permission denied                | Verify IAM policies for deploy + `bedrock-agentcore:InvokeAgentRuntime`                                |
| `codebuild:CreateProject` denied | GitHub secrets use invoke-only user; attach `deploy/github-actions-iam-policy.json` or use deploy user |
| Connection refused (DB)          | Security groups / VPC — runtime must reach Aurora                                                      |
| SSL / unexpected eof (DB)        | Add `?sslmode=require` to Aurora URLs (auto-applied in `config.py` for `*.rds.amazonaws.com`)          |
| Runtime env wiped                | Never run bare `agentcore deploy` — always pass `--env` flags (see `deploy-agentcore.sh`)              |
| Model / embedding errors         | Enable Bedrock model access in console; match `EMBEDDING_DIM` to vectors                               |
| Package too large (>250 MB)      | Re-run export with extra `--prune` flags, or switch to container deploy (toolkit generates Dockerfile) |
| Port 8080 in use (local)         | Stop other AgentCore local processes                                                                   |

## Cleanup

```powershell
agentcore destroy
```

## Files in this folder

| File                              | Purpose                                      |
| --------------------------------- | -------------------------------------------- |
| `env.agentcore.example`           | Template env vars for runtime                |
| `bedrock_agentcore.yaml`          | Committed AgentCore toolkit config (CI-safe) |
| `deploy-agentcore.sh`             | Deploy script for CI and local bash          |
| `github-actions-iam-policy.json`  | IAM policy for GitHub Actions deploy user    |
| `export-requirements.ps1` / `.sh` | Regenerate `requirements.txt` from `uv.lock` |
| `invoke_agent.py`                 | Post-deploy boto3 smoke test                 |

## References

- [AgentCore Runtime quickstart](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html)
- [Direct code deployment](https://aws.amazon.com/blogs/machine-learning/iterate-faster-with-amazon-bedrock-agentcore-runtime-direct-code-deployment/)
- [Starter toolkit CLI](https://aws.github.io/bedrock-agentcore-starter-toolkit/api-reference/cli.html)
