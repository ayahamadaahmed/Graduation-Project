$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

Write-Host ""
Write-Host "Installed dependencies."
Write-Host "Edit .env before testing the database connection."
Write-Host "DB_NAME in a new .env is a placeholder: set the approved database"
Write-Host "explicitly, then check it without connecting: python -m app.core.preflight"
