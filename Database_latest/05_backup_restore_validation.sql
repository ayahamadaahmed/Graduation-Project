/* =====================================================================
   MedMind - Sprint "Database Completion"  |  Script 05: Backup / restore validation
   Proves the database can be backed up and restored without loss:
     1. fingerprint every table (row count + checksum)
     2. full COPY_ONLY backup WITH CHECKSUM  (does not disturb your backup chain)
     3. RESTORE VERIFYONLY WITH CHECKSUM
     4. restore into a NEW database  <name>_RestoreTest
     5. DBCC CHECKDB on the restored copy
     6. compare fingerprints + object counts (tables, FKs, checks, indexes, triggers, views)
   Leaves the original database untouched. Output: one PASS/FAIL table at the end.

   BEFORE RUNNING
   * Edit @backup_dir: the folder must EXIST and be writable by the SQL Server
     service account (not by you). It is on the SERVER's disk.
   * Select the MedMind database in SSMS.
   * Needs permission to BACKUP/RESTORE (sysadmin or dbcreator + db_owner).
   * After it finishes, run 04_integrity_and_tenant_checks.sql with the
     <name>_RestoreTest database selected to repeat the integrity checks on the copy.
   ===================================================================== */
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.providers', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
SET NOCOUNT ON;

DECLARE @backup_dir   nvarchar(260) = N'C:\SQLBackups\';   -- <<< EDIT: must exist, ends with a backslash
DECLARE @drop_restored bit = 0;                            -- 1 = drop <name>_RestoreTest when finished

DECLARE @db sysname = DB_NAME();
DECLARE @restored sysname = @db + N'_RestoreTest';
DECLARE @file nvarchar(400) = @backup_dir + @db + N'_sprint_' + FORMAT(SYSDATETIME(), 'yyyyMMdd_HHmmss') + N'.bak';
DECLARE @sql nvarchar(max), @name sysname, @move nvarchar(max) = N'';
DECLARE @data_dir nvarchar(260) = CONVERT(nvarchar(260), SERVERPROPERTY('InstanceDefaultDataPath'));
DECLARE @log_dir  nvarchar(260) = CONVERT(nvarchar(260), SERVERPROPERTY('InstanceDefaultLogPath'));

DROP TABLE IF EXISTS #res, #before, #after, #tbl;
CREATE TABLE #res (id int IDENTITY(1,1), step varchar(60), status varchar(8), detail nvarchar(1000));
CREATE TABLE #before (t sysname, n bigint, ck int NULL);
CREATE TABLE #after  (t sysname, n bigint, ck int NULL);
CREATE TABLE #tbl (t sysname);

BEGIN TRY
    IF DB_ID(@restored) IS NOT NULL
        RAISERROR(N'A database named %s already exists. Drop it or rename it first.', 16, 1, @restored);

    /* ---- 1. fingerprint the original ---- */
    INSERT INTO #tbl SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID(N'dbo') ORDER BY name;
    DECLARE c1 CURSOR LOCAL FAST_FORWARD FOR SELECT t FROM #tbl;
    OPEN c1; FETCH NEXT FROM c1 INTO @name;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @sql = N'SELECT N''' + REPLACE(@name, '''', '''''') + N''', COUNT_BIG(*), CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM '
                 + QUOTENAME(@db) + N'.dbo.' + QUOTENAME(@name);
        INSERT INTO #before (t, n, ck) EXEC (@sql);
        FETCH NEXT FROM c1 INTO @name;
    END
    CLOSE c1; DEALLOCATE c1;
    INSERT INTO #res (step, status, detail) SELECT '1 fingerprint original', 'PASS', CONCAT(COUNT(*), N' tables, ', SUM(n), N' rows') FROM #before;

    /* ---- 2. backup ---- */
    SET @sql = N'BACKUP DATABASE ' + QUOTENAME(@db) + N' TO DISK = N''' + REPLACE(@file, '''', '''''')
             + N''' WITH COPY_ONLY, CHECKSUM, INIT, STATS = 10';
    EXEC (@sql);
    INSERT INTO #res (step, status, detail) VALUES ('2 backup (COPY_ONLY, CHECKSUM)', 'PASS', @file);

    /* ---- 3. verify the backup file ---- */
    SET @sql = N'RESTORE VERIFYONLY FROM DISK = N''' + REPLACE(@file, '''', '''''') + N''' WITH CHECKSUM';
    EXEC (@sql);
    INSERT INTO #res (step, status, detail) VALUES ('3 RESTORE VERIFYONLY', 'PASS', N'backup file is readable and checksums match');

    /* ---- 4. restore under a new name ---- */
    SELECT @move = @move + N', MOVE N''' + REPLACE(mf.name, '''', '''''') + N''' TO N'''
         + CASE WHEN mf.type = 1 THEN @log_dir ELSE @data_dir END + @restored + N'_' + mf.name
         + CASE WHEN mf.type = 1 THEN N'.ldf' ELSE N'.mdf' END + N''''
    FROM sys.master_files mf WHERE mf.database_id = DB_ID(@db) AND mf.type IN (0, 1);

    SET @sql = N'RESTORE DATABASE ' + QUOTENAME(@restored) + N' FROM DISK = N''' + REPLACE(@file, '''', '''''')
             + N''' WITH CHECKSUM, RECOVERY, STATS = 10' + @move;
    EXEC (@sql);
    INSERT INTO #res (step, status, detail) VALUES ('4 restore as ' + @restored, 'PASS', N'restore completed');

    /* ---- 5. physical + logical consistency of the restored copy ---- */
    SET @sql = N'DBCC CHECKDB (N''' + REPLACE(@restored, '''', '''''') + N''') WITH NO_INFOMSGS, ALL_ERRORMSGS';
    EXEC (@sql);
    INSERT INTO #res (step, status, detail) VALUES ('5 DBCC CHECKDB (restored)', 'PASS', N'no consistency errors');

    /* ---- 6. compare fingerprints ---- */
    DECLARE c2 CURSOR LOCAL FAST_FORWARD FOR SELECT t FROM #tbl;
    OPEN c2; FETCH NEXT FROM c2 INTO @name;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @sql = N'SELECT N''' + REPLACE(@name, '''', '''''') + N''', COUNT_BIG(*), CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM '
                 + QUOTENAME(@restored) + N'.dbo.' + QUOTENAME(@name);
        INSERT INTO #after (t, n, ck) EXEC (@sql);
        FETCH NEXT FROM c2 INTO @name;
    END
    CLOSE c2; DEALLOCATE c2;

    INSERT INTO #res (step, status, detail)
    SELECT '6a table fingerprints', CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
           CASE WHEN COUNT(*) = 0 THEN N'all tables: same row count and checksum'
                ELSE CONCAT(COUNT(*), N' table(s) differ: ', STRING_AGG(b.t, N', ')) END
    FROM #before b
    LEFT JOIN #after a ON a.t = b.t
    WHERE a.t IS NULL OR a.n <> b.n OR ISNULL(a.ck, 0) <> ISNULL(b.ck, 0);

    /* ---- 6b. object counts must match ---- */
    DECLARE @o nvarchar(max) = N'', @r nvarchar(max) = N'';
    SET @sql = N'SELECT @out = CONCAT((SELECT COUNT(*) FROM ' + QUOTENAME(@db) + N'.sys.tables), ''/'', (SELECT COUNT(*) FROM ' + QUOTENAME(@db)
             + N'.sys.foreign_keys), ''/'', (SELECT COUNT(*) FROM ' + QUOTENAME(@db) + N'.sys.check_constraints), ''/'', (SELECT COUNT(*) FROM ' + QUOTENAME(@db)
             + N'.sys.indexes WHERE object_id > 100), ''/'', (SELECT COUNT(*) FROM ' + QUOTENAME(@db) + N'.sys.triggers), ''/'', (SELECT COUNT(*) FROM ' + QUOTENAME(@db) + N'.sys.views))';
    EXEC sp_executesql @sql, N'@out nvarchar(max) OUTPUT', @out = @o OUTPUT;
    SET @sql = REPLACE(@sql, QUOTENAME(@db), QUOTENAME(@restored));
    EXEC sp_executesql @sql, N'@out nvarchar(max) OUTPUT', @out = @r OUTPUT;
    INSERT INTO #res (step, status, detail)
    VALUES ('6b object counts (tables/FK/CK/index/trigger/view)', CASE WHEN @o = @r THEN 'PASS' ELSE 'FAIL' END,
            CONCAT(N'original ', @o, N'  restored ', @r));

    IF @drop_restored = 1
    BEGIN
        SET @sql = N'ALTER DATABASE ' + QUOTENAME(@restored) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE ' + QUOTENAME(@restored);
        EXEC (@sql);
        INSERT INTO #res (step, status, detail) VALUES ('7 cleanup', 'PASS', N'restored test database dropped');
    END
    ELSE
        INSERT INTO #res (step, status, detail) VALUES ('7 cleanup', 'PASS', CONCAT(N'kept ', @restored, N' - run script 04 against it, then drop it'));
END TRY
BEGIN CATCH
    INSERT INTO #res (step, status, detail) VALUES ('ERROR', 'FAIL', CONCAT(N'#', ERROR_NUMBER(), N' line ', ERROR_LINE(), N': ', ERROR_MESSAGE()));
END CATCH;

SELECT step, status, detail FROM #res ORDER BY id;
SELECT t AS table_name, n AS rows_original FROM #before ORDER BY t;
GO
SET NOEXEC OFF;
GO
