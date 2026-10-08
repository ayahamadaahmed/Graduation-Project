$ErrorActionPreference = "Stop"

$tenant = "clinic-001"
$aiBase = "http://127.0.0.1:8001"
$apiBase = "http://127.0.0.1:8001"

function Send-MedMindMessage {
    param(
        [string]$SessionId,
        [string]$Message
    )

    $body = @{
        session_id = $SessionId
        message    = $Message
        channel    = "web"
    } | ConvertTo-Json

    return Invoke-RestMethod `
        -Uri "$aiBase/api/v1/ai/chat" `
        -Method Post `
        -Headers @{
            "X-Tenant-ID" = $tenant
        } `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
}


# ============================================================
# TEST 1
# Doctor-first booking
# ============================================================

$session1 = "regression-doctor-first-" + [Guid]::NewGuid().ToString("N")

$result1 = Send-MedMindMessage `
    -SessionId $session1 `
    -Message "عايزة احجز مع دكتور ماهر"

if ($result1.stage -ne "awaiting_date") {

    throw (
        "Doctor-first regression failed. " +
        "Expected awaiting_date, got: " +
        $result1.stage
    )
}

Write-Host "PASS: doctor-first booking"


# ============================================================
# Resolve Dr Maher from backend
# ============================================================

$doctors = Invoke-RestMethod `
    -Uri "$apiBase/api/v1/doctors" `
    -Method Get `
    -Headers @{
        "X-Tenant-ID" = $tenant
    }

$doctor = $doctors |
    Where-Object {
        $_.full_name_en -eq "Dr. Maher Mahmoud"
    } |
    Select-Object -First 1

if (-not $doctor) {
    throw "Dr. Maher Mahmoud was not found."
}


# ============================================================
# Find first real available slot
# ============================================================

$foundDate = $null
$foundTime = $null

for ($i = 0; $i -le 30; $i++) {

    $date = (
        Get-Date
    ).Date.AddDays($i).ToString(
        "yyyy-MM-dd"
    )

    $slots = Invoke-RestMethod `
        -Uri "$apiBase/api/v1/slots?slot_date=$date&doctor_id=$($doctor.id)&limit=100" `
        -Method Get `
        -Headers @{
            "X-Tenant-ID" = $tenant
        }

    $available = $slots |
        Where-Object {
            $_.status -eq "available"
        } |
        Select-Object -First 1

    if ($available) {

        $foundDate = $date
        $foundTime = (
            $available.start_time
        ).Substring(0, 5)

        break
    }
}

if (-not $foundDate) {
    throw "No available slot found in next 30 days."
}


# ============================================================
# TEST 2
# Contextual time resolution
# ============================================================

$session2 = "regression-time-" + [Guid]::NewGuid().ToString("N")

$result2 = Send-MedMindMessage `
    -SessionId $session2 `
    -Message "عايزة احجز مع دكتور ماهر يوم $foundDate"

if ($result2.stage -ne "awaiting_time") {

    throw (
        "Expected awaiting_time, got: " +
        $result2.stage
    )
}

$result3 = Send-MedMindMessage `
    -SessionId $session2 `
    -Message $foundTime

if ($result3.stage -ne "awaiting_service") {

    throw (
        "Time regression failed. " +
        "Expected awaiting_service, got: " +
        $result3.stage
    )
}

if ($result3.intent -ne "provide_time") {

    throw (
        "Expected provide_time, got: " +
        $result3.intent
    )
}

if ($result3.route -ne "book_appointment") {

    throw (
        "Expected book_appointment route, got: " +
        $result3.route
    )
}

Write-Host "PASS: contextual time resolution"
Write-Host ""
Write-Host "BOOKING REGRESSION TESTS PASSED"