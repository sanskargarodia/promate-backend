#!/usr/bin/env bash
# Deploy ProMate to Bedrock AgentCore (container / CodeBuild).
# Used by GitHub Actions and can be run locally with env vars set.
#
# Required env:
#   ANTHROPIC_API_KEY, DATABASE_URL, DATABASE_URL_SYNC
# AWS credentials via standard provider chain (env or instance role).

set -euo pipefail
cd "$(dirname "$0")/.."

export AGENTCORE_SUPPRESS_RECOMMENDATION=1
export NO_COLOR=1
export PYTHONIOENCODING=utf-8

echo "Exporting requirements.txt..."
bash deploy/export-requirements.sh

echo "Installing AgentCore deploy CLI..."
python -m pip install --quiet bedrock-agentcore-starter-toolkit

echo "Using committed AgentCore config..."
cp deploy/bedrock_agentcore.yaml .bedrock_agentcore.yaml

ENV_KEYS=(
  ANTHROPIC_API_KEY
  DATABASE_URL
  DATABASE_URL_SYNC
  AWS_REGION
  APP_ENV
  LOG_LEVEL
  EMBEDDINGS_PROVIDER
  FASTEMBED_MODEL
  EMBEDDING_DIM
  ANTHROPIC_MODEL_ID
  ANTHROPIC_GUARDRAIL_MODEL_ID
)

ENV_ARGS=()
for key in "${ENV_KEYS[@]}"; do
  value="${!key:-}"
  if [[ -n "$value" ]]; then
    ENV_ARGS+=(--env "${key}=${value}")
  fi
done

if [[ ${#ENV_ARGS[@]} -eq 0 ]]; then
  echo "No runtime env vars set. Pass secrets via --env or environment." >&2
  exit 1
fi

echo "Deploying AgentCore runtime..."
agentcore deploy "${ENV_ARGS[@]}"
