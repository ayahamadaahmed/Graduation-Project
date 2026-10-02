# MedMind Booking Backend — Milestone 1

This is a clean FastAPI backend that reads the existing
`MedMind_Booking_DB` SQL Server database.

It contains:

- Database connection and health checks.
- Tenant resolution through the `X-Tenant-ID` header.
- Read-only providers, branches, specialties, services, doctors, and slots.
- No AI, LangGraph, MCP, RAG, or old project imports.
- No database migrations or write operations yet.

## 1. Open the backend folder

```powershell
cd "D:\University\Graduation Project\AI Agents\healthcare-ai-platform\backend"
conda activate healthcare-booking311
```

## 2. Install dependencies

```powershell
.\setup.ps1
```

Or:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## 3. Check the installed SQL Server ODBC driver

```powershell
Get-OdbcDriver |
Where-Object { $_.Name -like "*SQL Server*" } |
Select-Object Name, Platform
```

The driver name in `.env` must exactly match an installed driver.

## 4. Configure `.env`

Windows authentication example:

```env
DB_SERVER=localhost
DB_NAME=MedMind_Booking_DB
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_TRUSTED_CONNECTION=true
DB_ENCRYPT=true
DB_TRUST_SERVER_CERTIFICATE=true
```

Named SQL Server instance example:

```env
DB_SERVER=localhost\SQLEXPRESS
```

SQL authentication example:

```env
DB_TRUSTED_CONNECTION=false
DB_USER=your_user
DB_PASSWORD=your_password
```

## 5. Run local checks

```powershell
.\check.ps1
```

These tests do not modify the database.

## 6. Start the API

```powershell
.\run.ps1
```

Open:

- Swagger: `http://127.0.0.1:8000/docs`
- Liveness: `http://127.0.0.1:8000/health/live`
- Database readiness: `http://127.0.0.1:8000/health`

## 7. Test with PowerShell

Use a real `tenant_key` from `dbo.providers`.

```powershell
$headers = @{
    "X-Tenant-ID" = "clinic-001"
}

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/providers/current" `
    -Headers $headers

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/branches" `
    -Headers $headers

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/specialties" `
    -Headers $headers

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/services" `
    -Headers $headers

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/doctors" `
    -Headers $headers

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/slots?slot_date=2026-08-08" `
    -Headers $headers
```

## Expected milestone result

- `/health/live` returns HTTP 200 without using the database.
- `/health` returns `database: connected`.
- Catalog endpoints return only records belonging to `X-Tenant-ID`.
- All slot results have `status = available`.

The next milestone adds patient identity and transactional appointment
creation, cancellation, confirmation, and rescheduling.
