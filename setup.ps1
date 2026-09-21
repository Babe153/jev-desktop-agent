$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Please install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}
uv sync --python 3.13
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
uv run playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
Write-Host 'Ready. Set TYPESAFE_API_KEY in .env, then run: uv run python main.py'
