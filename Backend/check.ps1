$ErrorActionPreference = "Stop"

Write-Host "Compiling Python files..."
python -m compileall app

if ($LASTEXITCODE -ne 0) {
    Write-Error "Python compilation failed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Running tests..."
python -m pytest

if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Local checks passed."