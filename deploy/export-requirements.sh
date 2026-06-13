#!/usr/bin/env bash
# Regenerate requirements.txt from uv.lock (runtime deps for AgentCore direct_code_deploy).
# Run from promate-backend/:  ./deploy/export-requirements.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "Exporting requirements.txt (runtime, no scrape stack)..."
uv export --no-dev --no-hashes \
    --prune playwright \
    --prune beautifulsoup4 \
    --prune lxml \
    -o requirements.txt

echo "Done."
