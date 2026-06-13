# Regenerate requirements.txt from uv.lock (runtime deps for AgentCore direct_code_deploy).
# Run from promate-backend/:  .\deploy\export-requirements.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "Exporting requirements.txt (runtime, no scrape stack)..."
uv export --no-dev --no-hashes `
    --prune playwright `
    --prune beautifulsoup4 `
    --prune lxml `
    -o requirements.txt

Write-Host "Done."
