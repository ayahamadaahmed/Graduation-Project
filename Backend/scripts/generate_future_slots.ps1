$ErrorActionPreference = "Stop"

$apiBase = "http://127.0.0.1:8001"

$dateFrom = (
    Get-Date
).Date.ToString(
    "yyyy-MM-dd"
)

$dateTo = (
    Get-Date
).Date.AddDays(60).ToString(
    "yyyy-MM-dd"
)

$tenants = @(
    "clinic-001",
    "hospital-001"
)

foreach ($tenant in $tenants) {

    Write-Host ""
    Write-Host "Generating slots for $tenant"

    $body = @{
        date_from = $dateFrom
        date_to   = $dateTo
    } | ConvertTo-Json

    $result = Invoke-RestMethod `
        -Uri "$apiBase/api/v1/admin/working-hours/generate-slots" `
        -Method Post `
        -Headers @{
            "X-Tenant-ID" = $tenant
        } `
        -ContentType "application/json" `
        -Body $body

    Write-Host "Working hours: $($result.working_hours_used)"
    Write-Host "Created:       $($result.created_slots)"
    Write-Host "Existing:      $($result.skipped_existing_slots)"
}