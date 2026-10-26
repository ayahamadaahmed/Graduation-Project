$ErrorActionPreference = "Stop"
$agentPath = Join-Path $PSScriptRoot "agent"

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$agentPath;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $agentPath
}

conda run --no-capture-output -n healthcare-booking311 python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
