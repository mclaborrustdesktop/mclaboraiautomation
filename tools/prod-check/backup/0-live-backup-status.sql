-- READ-ONLY REPORT - changes nothing. For the client's SQL Server administrator, on the LIVE server, in SQL Server
-- Management Studio (Results to Grid, then Results -> Save As to send the owner). Reads only the server's own backup
-- history (msdb) and database properties: no business row is read, no backup is taken, nothing is restored.
--
-- Before Execute: replace LIVE-HOST (one place below) with the server name from SELECT SERVERPROPERTY('ServerName'),
-- including \SQLEXPRESS. The script stops on any other server.
--
-- Result grids:
--   1 server          name, edition, version, SQL Server Agent present (Express: never), start time
--   2 database        McLabor: state, recovery model, page verify, size, last known backup dates (full / differential / log)
--   3 latest by type  the newest FULL, DIFFERENTIAL and LOG backup of McLabor: when, how old (hours), copy-only, checksums,
--                     damaged flag, size, who, file, and whether that file still exists on this server (xp_fileexist)
--   4 last 15 backups every backup of McLabor recorded here, newest first
--   5 restores        every restore ever done on this server (a restore test is the only proof a backup works)
--   6 jobs            scheduled SQL Agent jobs (none expected on Express: backups then come from a Windows task or a tool)
--   7 other databases all databases on the instance (looking for a second McLabor-like database)
--   8 verdict         plain-language verdict on the newest full backup

IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'LIVE-HOST\SQLEXPRESS'
BEGIN
    RAISERROR('Wrong server. Edit LIVE-HOST at the top of this file to this server''s name first. Nothing was read.', 16, 1);
    SET NOEXEC ON;
END
GO

-- 1 server
SELECT CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) AS server_name,
       CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition,
       CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(32)) AS product_version,
       CASE WHEN EXISTS (SELECT 1 FROM sys.dm_server_services WHERE servicename LIKE N'SQL Server Agent%' AND status_desc = N'Running') THEN N'running'
            WHEN EXISTS (SELECT 1 FROM sys.dm_server_services WHERE servicename LIKE N'SQL Server Agent%') THEN N'installed but not running (Express cannot run it: backups need a Windows scheduled task or a backup tool)'
            ELSE N'absent' END AS sql_agent,
       (SELECT sqlserver_start_time FROM sys.dm_os_sys_info) AS sql_server_started,
       SYSDATETIME() AS report_time;

-- 2 database
SELECT d.name, d.state_desc, d.recovery_model_desc, d.page_verify_option_desc,
       (SELECT SUM(CAST(size AS bigint)) * 8 / 1024 FROM sys.master_files mf WHERE mf.database_id = d.database_id) AS allocated_mb,
       (SELECT MAX(backup_finish_date) FROM msdb.dbo.backupset bs WHERE bs.database_name = d.name AND bs.type = 'D') AS last_full_backup,
       (SELECT MAX(backup_finish_date) FROM msdb.dbo.backupset bs WHERE bs.database_name = d.name AND bs.type = 'I') AS last_differential_backup,
       (SELECT MAX(backup_finish_date) FROM msdb.dbo.backupset bs WHERE bs.database_name = d.name AND bs.type = 'L') AS last_log_backup
FROM sys.databases d WHERE d.name = N'McLabor';

-- 3 latest by type, with the file's existence
IF OBJECT_ID('tempdb..#latest') IS NOT NULL DROP TABLE #latest;
SELECT x.type_name, bs.backup_finish_date, DATEDIFF(hour, bs.backup_finish_date, SYSDATETIME()) AS age_hours,
       bs.is_copy_only, bs.has_backup_checksums, bs.is_damaged, CAST(bs.backup_size / 1048576.0 AS decimal(12,1)) AS size_mb,
       bs.user_name AS taken_by, bmf.physical_device_name AS backup_file, CAST(NULL AS int) AS file_exists
INTO #latest
FROM (VALUES ('D', N'FULL'), ('I', N'DIFFERENTIAL'), ('L', N'LOG')) AS x(type_code, type_name)
CROSS APPLY (SELECT TOP 1 * FROM msdb.dbo.backupset b WHERE b.database_name = N'McLabor' AND b.type = x.type_code ORDER BY b.backup_finish_date DESC) bs
JOIN msdb.dbo.backupmediafamily bmf ON bmf.media_set_id = bs.media_set_id;

DECLARE @f nvarchar(400), @t nvarchar(20);
DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT type_name, backup_file FROM #latest;
OPEN c; FETCH NEXT FROM c INTO @t, @f;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF OBJECT_ID('tempdb..#fe') IS NOT NULL DROP TABLE #fe;
    CREATE TABLE #fe (file_exists int, is_directory int, parent_exists int);
    INSERT INTO #fe EXEC master.dbo.xp_fileexist @f;
    UPDATE #latest SET file_exists = (SELECT file_exists FROM #fe) WHERE type_name = @t;
    FETCH NEXT FROM c INTO @t, @f;
END
CLOSE c; DEALLOCATE c;
SELECT * FROM #latest ORDER BY CASE type_name WHEN N'FULL' THEN 1 WHEN N'DIFFERENTIAL' THEN 2 ELSE 3 END;

-- 4 last 15 backups
SELECT TOP 15 bs.backup_finish_date, bs.type, bs.is_copy_only, bs.has_backup_checksums, bs.is_damaged,
       CAST(bs.backup_size / 1048576.0 AS decimal(12,1)) AS size_mb, bs.user_name, bs.server_name, bmf.physical_device_name
FROM msdb.dbo.backupset bs JOIN msdb.dbo.backupmediafamily bmf ON bmf.media_set_id = bs.media_set_id
WHERE bs.database_name = N'McLabor' ORDER BY bs.backup_finish_date DESC;

-- 5 restores ever done here
SELECT rh.restore_date, rh.destination_database_name, rh.restore_type, rh.replace, bs.database_name AS from_database,
       bs.server_name AS from_server, bs.backup_finish_date AS from_backup_of, rh.user_name
FROM msdb.dbo.restorehistory rh JOIN msdb.dbo.backupset bs ON bs.backup_set_id = rh.backup_set_id
ORDER BY rh.restore_date DESC;

-- 6 scheduled jobs (Agent)
SELECT j.name, j.enabled, j.date_modified FROM msdb.dbo.sysjobs j ORDER BY j.name;

-- 7 all databases
SELECT name, state_desc, recovery_model_desc, create_date FROM sys.databases WHERE database_id > 4 ORDER BY name;

-- 8 verdict
SELECT CASE
         WHEN NOT EXISTS (SELECT 1 FROM #latest WHERE type_name = N'FULL') THEN N'NO FULL BACKUP of McLabor is recorded on this server. Take a COPY_ONLY full backup with checksum (script 4) before any change.'
         WHEN (SELECT age_hours FROM #latest WHERE type_name = N'FULL') > 24 THEN N'The newest full backup is older than 24 hours (see age_hours). Take a COPY_ONLY full backup with checksum (script 4) before any change.'
         WHEN (SELECT file_exists FROM #latest WHERE type_name = N'FULL') = 0 THEN N'The newest full backup is recent but its FILE IS MISSING from this server. Locate the copy, or take a COPY_ONLY full backup (script 4).'
         WHEN (SELECT has_backup_checksums FROM #latest WHERE type_name = N'FULL') = 0 THEN N'The newest full backup is recent and present but was taken WITHOUT checksums: run RESTORE VERIFYONLY on it, or take a COPY_ONLY full backup with checksum (script 4).'
         ELSE N'A recent full backup with checksums exists and its file is present. Verify it with RESTORE VERIFYONLY ... WITH CHECKSUM (or a restore test) and record the result.'
       END AS verdict,
       N'Grid 5 shows whether a restore test was ever done here; a backup is only proven when it has been restored once.' AS note;
GO
SET NOEXEC OFF;
GO
