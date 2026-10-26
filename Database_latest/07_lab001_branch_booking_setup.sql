/* =====================================================================
   MedMind - Script 07: lab-001 (Alfa Labs) branch-level booking setup
   Labs book by branch + test, without a doctor (Alembic f4b8d2c6a1e3).

   Does three things for lab-001 only:
     1. sets the missing 3-letter MRN code of each branch (never overwrites);
     2. adds branch-level weekly opening hours (doctor_id NULL);
     3. generates @slot_days days of available slots from those hours.

   * NOTHING IS ASSUMED. The MRN codes and opening hours below are business
     values and are empty on purpose: the script stops until they are filled.
   * DRY RUN BY DEFAULT: @commit = 0 rolls everything back and only shows
     the summary. Set @commit = 1 to keep the data.
   * Refuses to run unless DB_NAME() equals @expected_db.
   * Idempotent: existing codes, hours and slots are never duplicated.
   * Run with QUOTED_IDENTIFIER ON (SSMS default; sqlcmd needs -I),
     required by the filtered unique indexes.

   Day-of-week follows the app (Python weekday): Mon=0 ... Sat=5, Sun=6.
   ===================================================================== */
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
GO
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.providers', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the restored MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

/* ======================= VALUES YOU MUST PROVIDE =======================
   !!! MOCK / NOT REAL OPERATING HOURS !!!
   The MRN codes and hours below are TEMPORARY MOCK DATA for the isolated
   audit copy MedMind_Audit_Final2 only. They are NOT Alfa Labs' real
   codes or opening hours. Replace them with confirmed business values
   (and change @expected_db) before using this script anywhere else.
   ======================================================================= */
DECLARE @expected_db sysname = N'MedMind_Audit_Final2';   -- MOCK target: isolated audit copy only
DECLARE @commit bit = 0;               -- <<< 0 = dry run (rollback), 1 = keep the data
DECLARE @slot_days int = 14;           -- availability horizon starting today (Cairo date)

DROP TABLE IF EXISTS #mrn, #hours;
CREATE TABLE #mrn   (branch_code varchar(50) COLLATE DATABASE_DEFAULT, mrn_code char(3) COLLATE DATABASE_DEFAULT NULL);
CREATE TABLE #hours (branch_code varchar(50) COLLATE DATABASE_DEFAULT, days varchar(20) COLLATE DATABASE_DEFAULT,
                     start_time time(0), end_time time(0), slot_minutes int);

-- MRN code per branch: exactly 3 letters A-Z, unique inside lab-001.
INSERT INTO #mrn (branch_code, mrn_code) VALUES
    (N'HELIOPOLIS', N'HLP'),   -- MOCK MRN code (temporary)
    (N'MAADI',      N'MDI');   -- MOCK MRN code (temporary)

-- Opening hours per branch (one row per continuous shift).
-- days = comma list of 0..6 (Mon=0 ... Sun=6); slot_minutes 5..240.
-- MOCK / NOT REAL OPERATING HOURS: Saturday-Thursday (5,6,0,1,2,3), Friday closed.
INSERT INTO #hours (branch_code, days, start_time, end_time, slot_minutes) VALUES
    (N'HELIOPOLIS', N'5,6,0,1,2,3', '09:00', '17:00', 15),   -- MOCK hours
    (N'MAADI',      N'5,6,0,1,2,3', '10:00', '18:00', 15);   -- MOCK hours
/* ======================================================================= */

DECLARE @lab uniqueidentifier = (SELECT id FROM dbo.providers WHERE tenant_key = N'lab-001' AND org_type = N'diagnostic_lab');
DECLARE @errors nvarchar(max) = N'';

IF @expected_db IS NULL OR @expected_db <> DB_NAME()
    SET @errors += CONCAT(N'@expected_db must equal the current database (', DB_NAME(), N'). ');
IF @lab IS NULL
    SET @errors += N'lab-001 diagnostic_lab provider not found. ';
IF COLUMNPROPERTY(OBJECT_ID(N'dbo.doctor_availability_slots'), N'doctor_id', N'AllowsNull') <> 1
    SET @errors += N'Run alembic upgrade f4b8d2c6a1e3 first (doctor_id must be nullable). ';
IF EXISTS (SELECT 1 FROM #mrn m JOIN dbo.branches b ON b.provider_id = @lab AND b.code = m.branch_code
           WHERE b.mrn_code IS NULL AND m.mrn_code IS NULL)
    SET @errors += N'Fill the MRN code of every lab-001 branch that has none. ';
IF EXISTS (SELECT 1 FROM #mrn WHERE mrn_code IS NOT NULL
           AND UPPER(mrn_code) COLLATE Latin1_General_BIN NOT LIKE '[A-Z][A-Z][A-Z]')
    SET @errors += N'MRN codes must be exactly 3 letters A-Z. ';
IF EXISTS (SELECT UPPER(code) FROM (SELECT mrn_code AS code FROM #mrn WHERE mrn_code IS NOT NULL
                                    UNION ALL
                                    SELECT b.mrn_code FROM dbo.branches b
                                    WHERE b.provider_id = @lab AND b.mrn_code IS NOT NULL
                                      AND b.code NOT IN (SELECT branch_code FROM #mrn WHERE mrn_code IS NOT NULL)) c
           GROUP BY UPPER(code) HAVING COUNT(*) > 1)
    SET @errors += N'MRN codes must be unique within lab-001. ';
IF EXISTS (SELECT 1 FROM #mrn m WHERE NOT EXISTS
           (SELECT 1 FROM dbo.branches b WHERE b.provider_id = @lab AND b.code = m.branch_code AND b.is_active = 1))
    SET @errors += N'#mrn lists a branch that is not an active lab-001 branch. ';
IF EXISTS (SELECT 1 FROM #hours h WHERE NOT EXISTS
           (SELECT 1 FROM dbo.branches b WHERE b.provider_id = @lab AND b.code = h.branch_code AND b.is_active = 1))
    SET @errors += N'#hours lists a branch that is not an active lab-001 branch. ';
IF EXISTS (SELECT 1 FROM #hours WHERE start_time IS NULL OR end_time IS NULL OR end_time <= start_time
           OR slot_minutes IS NULL OR slot_minutes NOT BETWEEN 5 AND 240)
    SET @errors += N'Each #hours row needs start < end and slot_minutes 5..240. ';
IF EXISTS (SELECT 1 FROM #hours h CROSS APPLY STRING_SPLIT(h.days, ',') s
           WHERE TRY_CAST(LTRIM(RTRIM(s.value)) AS int) IS NULL
              OR TRY_CAST(LTRIM(RTRIM(s.value)) AS int) NOT BETWEEN 0 AND 6)
    SET @errors += N'#hours days must be a comma list of 0..6. ';
IF @slot_days NOT BETWEEN 1 AND 90
    SET @errors += N'@slot_days must be 1..90. ';

IF @errors <> N''
BEGIN
    SET @errors = N'Nothing was changed. ' + @errors;
    THROW 50070, @errors, 1;   -- aborts the batch
END

BEGIN TRY
BEGIN TRANSACTION;

/* ---------- 1. MRN codes (only where missing) ---------- */
UPDATE b SET mrn_code = UPPER(m.mrn_code), updated_at = SYSDATETIMEOFFSET()
FROM dbo.branches b
JOIN #mrn m ON m.branch_code = b.code
WHERE b.provider_id = @lab AND b.mrn_code IS NULL AND m.mrn_code IS NOT NULL;

/* ---------- 2. branch-level weekly hours (doctor_id NULL) ---------- */
INSERT INTO dbo.doctor_working_hours (id, provider_id, doctor_id, branch_id, day_of_week, start_time, end_time,
                                      slot_duration_minutes, is_active, created_at, updated_at)
SELECT NEWID(), @lab, NULL, b.id, dd.dow, h.start_time, h.end_time, h.slot_minutes, 1,
       SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #hours h
JOIN dbo.branches b ON b.provider_id = @lab AND b.code = h.branch_code
CROSS APPLY (SELECT DISTINCT CAST(LTRIM(RTRIM(value)) AS int) AS dow FROM STRING_SPLIT(h.days, ',')) dd
WHERE NOT EXISTS (SELECT 1 FROM dbo.doctor_working_hours x
                  WHERE x.doctor_id IS NULL AND x.branch_id = b.id
                    AND x.day_of_week = dd.dow AND x.start_time = h.start_time)
  AND NOT EXISTS (SELECT 1 FROM dbo.doctor_working_hours x       -- no overlapping shift
                  WHERE x.doctor_id IS NULL AND x.branch_id = b.id AND x.is_active = 1
                    AND x.day_of_week = dd.dow
                    AND x.start_time < h.end_time AND x.end_time > h.start_time);

/* ---------- 3. slots (same rules as the app's slot generator) ---------- */
DECLARE @today date = CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'Egypt Standard Time' AS date);

;WITH n AS (
    SELECT TOP (@slot_days) CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS int) AS i FROM sys.all_objects
), days AS (
    SELECT DATEADD(day, n.i, @today) AS slot_date FROM n
), k AS (
    SELECT TOP (288) CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS int) AS j FROM sys.all_objects
)
INSERT INTO dbo.doctor_availability_slots (id, provider_id, doctor_id, branch_id, working_hours_id, slot_date, start_time, end_time,
                                           status, hold_expires_at, hold_reference, is_waitlist_fill, created_at, updated_at)
SELECT NEWID(), w.provider_id, NULL, w.branch_id, w.id, d.slot_date,
       DATEADD(minute, k.j * w.slot_duration_minutes, w.start_time),
       DATEADD(minute, (k.j + 1) * w.slot_duration_minutes, w.start_time),
       'available', NULL, NULL, 0, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM dbo.doctor_working_hours w
JOIN dbo.branches b ON b.id = w.branch_id AND b.is_active = 1
CROSS JOIN days d
CROSS JOIN k
WHERE w.provider_id = @lab AND w.doctor_id IS NULL AND w.is_active = 1
  AND ((DATEPART(weekday, d.slot_date) + @@DATEFIRST - 2) % 7) = w.day_of_week
  AND DATEDIFF(minute, w.start_time, w.end_time) >= (k.j + 1) * w.slot_duration_minutes
  AND NOT EXISTS (SELECT 1 FROM dbo.doctor_availability_slots x
                  WHERE x.doctor_id IS NULL AND x.branch_id = w.branch_id AND x.slot_date = d.slot_date
                    AND x.start_time = DATEADD(minute, k.j * w.slot_duration_minutes, w.start_time));

/* ---------- summary (visible even on a dry run) ---------- */
SELECT b.code AS branch_code, b.mrn_code,
       (SELECT COUNT(*) FROM dbo.doctor_working_hours w
        WHERE w.branch_id = b.id AND w.doctor_id IS NULL AND w.is_active = 1)                 AS branch_hour_rows,
       (SELECT COUNT(*) FROM dbo.doctor_availability_slots s
        WHERE s.branch_id = b.id AND s.doctor_id IS NULL AND s.status = 'available'
          AND s.slot_date >= @today)                                                        AS future_available_slots
FROM dbo.branches b
WHERE b.provider_id = @lab AND b.is_active = 1
ORDER BY b.code;

IF @commit = 1
BEGIN
    COMMIT TRANSACTION;
    PRINT N'COMMITTED. lab-001 MOCK MRN codes, hours and slots were saved (NOT REAL OPERATING HOURS).';
END
ELSE
BEGIN
    ROLLBACK TRANSACTION;
    PRINT N'DRY RUN (MOCK values). Nothing was saved. Set @commit = 1 to keep the data.';
END
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
GO
SET NOEXEC OFF;
GO
