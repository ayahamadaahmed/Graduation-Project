$ErrorActionPreference = "Stop"

conda run -n healthcare-booking311 python -m pip install -r requirements-prod.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

Write-Host ""
Write-Host "Installed dependencies."
Write-Host "Edit .env before testing the database connection."
