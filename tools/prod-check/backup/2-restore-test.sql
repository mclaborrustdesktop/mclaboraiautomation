-- PROPOSAL - NOT RUN. Needs the client's approval. Run in SQL Server Management Studio as a SQL Server administrator.
--
-- Proves the backup can be restored, by restoring it as a SEPARATE database called McLabor_RestoreTest.
-- It never touches the McLabor database: there is no REPLACE option anywhere in this file, the target name is
-- fixed, and the script stops if a database with that name already exists.
-- It needs about 2.3 GB of disk space for a few minutes. Remove the test copy afterwards with script 3.
--
-- BEFORE RUNNING: put the full path of the backup file (printed by script 1) between the quotes below.
-- Use a backup made by script 1. A backup made without checksums (such as the 2026-11-13 file in C:\ZZZ-SQL)
-- is refused by the CHECKSUM option below.

-- SAFETY: this script is for the STAGING copy only. It stops on any other server (for example LIVE-HOST).
IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\SQLEXPRESS'
BEGIN
    RAISERROR('Wrong server. This script only runs on DEV-PC\SQLEXPRESS (the restored copy). Nothing was done.', 16, 1);
    SET NOEXEC ON;  -- skips every remaining step of this script
END
GO

DECLARE @file nvarchar(400) = N'<<PATH-OF-THE-BACKUP-FILE>>';

IF @file LIKE N'%<<%'
BEGIN
    RAISERROR('Put the backup file path in @file first. Nothing was done.', 16, 1);
    SET NOEXEC ON;  -- skips every remaining step of this script
END
IF DB_ID(N'McLabor_RestoreTest') IS NOT NULL
BEGIN
    RAISERROR('A database named McLabor_RestoreTest already exists. Remove it with script 3 first. Nothing was done.', 16, 1);
    SET NOEXEC ON;
END

DECLARE @data nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log  nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath')  AS nvarchar(260));
DECLARE @mdf  nvarchar(400) = @data + N'McLabor_RestoreTest.mdf';
DECLARE @ldf  nvarchar(400) = @log  + N'McLabor_RestoreTest_log.ldf';

-- The logical file names inside the McLabor backup are '11-4-2021' and '11-4-2021_log'.
RESTORE DATABASE [McLabor_RestoreTest] FROM DISK = @file
    WITH CHECKSUM, RECOVERY, STATS = 10,
         MOVE N'11-4-2021'     TO @mdf,
         MOVE N'11-4-2021_log' TO @ldf;
GO

-- Full consistency check of the restored copy (reads only the test copy). No rows returned = no problems found.
DBCC CHECKDB (N'McLabor_RestoreTest') WITH NO_INFOMSGS;
GO

-- Compare row counts, table by table. This lists counts only - no record content.
-- Every row should say SAME. (A table that people edited after the backup was taken can differ.)
SELECT t.table_name, t.live_rows, r.test_rows, CASE WHEN t.live_rows = r.test_rows THEN 'SAME' ELSE 'DIFFERENT' END AS result
FROM (SELECT o.name AS table_name, SUM(p.row_count) AS live_rows
      FROM [McLabor].sys.dm_db_partition_stats p JOIN [McLabor].sys.objects o ON o.object_id = p.object_id
      WHERE o.type = 'U' AND p.index_id IN (0, 1) GROUP BY o.name) t
JOIN (SELECT o.name AS table_name, SUM(p.row_count) AS test_rows
      FROM [McLabor_RestoreTest].sys.dm_db_partition_stats p JOIN [McLabor_RestoreTest].sys.objects o ON o.object_id = p.object_id
      WHERE o.type = 'U' AND p.index_id IN (0, 1) GROUP BY o.name) r ON r.table_name = t.table_name
WHERE t.table_name IN (N'tblEmployee', N'tblEmployeeB', N'tblCustomer', N'tblProject', N'tblTracking', N'tblOfficeStaff')
ORDER BY t.table_name;

SELECT COUNT(*) AS tables_in_live FROM [McLabor].sys.objects WHERE type = 'U';
SELECT COUNT(*) AS tables_in_test FROM [McLabor_RestoreTest].sys.objects WHERE type = 'U';
GO

SET NOEXEC OFF;
GO
