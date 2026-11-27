-- PROPOSAL - NOT RUN. Needs the client's administrator approval. Run on the LIVE server in SQL Server Management Studio
-- as a SQL Server administrator, only if script 0 (0-live-backup-status.sql) showed no recent verified full backup.
--
-- Makes one COPY_ONLY full backup of McLabor with checksums and verifies the file. It only READS the database:
-- nobody is disconnected, nothing is restarted, no record is changed, and COPY_ONLY leaves any existing backup
-- routine (differential base, log chain) exactly as it was. Expected size about 1.7 GB (Express cannot compress),
-- expected time a few minutes while the office keeps working (the 1.7 GB copy took 17 seconds on the office PC).
--
-- Before Execute: 1) replace LIVE-HOST (one place) with the server name from SELECT SERVERPROPERTY('ServerName');
--                 2) check that the backup folder (printed first) has at least 4 GB free; to use another folder,
--                    set @folder to it (administrators-only folder: the file contains SSNs and bank details).

IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'LIVE-HOST\SQLEXPRESS'
BEGIN
    RAISERROR('Wrong server. Edit LIVE-HOST at the top of this file to this server''s name first. Nothing was done.', 16, 1);
    SET NOEXEC ON;
END
GO

DECLARE @folder nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260));  -- SQL Server's own backup folder
DECLARE @file   nvarchar(400) = @folder + N'\McLabor_LIVE_' + FORMAT(SYSDATETIME(), 'yyyy-MM-dd_HHmmss') + N'_full_copyonly.bak';
DECLARE @name   nvarchar(128) = N'McLabor full copy-only backup before the read-only login ' + CONVERT(nvarchar(16), SYSDATETIME(), 120);

PRINT N'Backing up to: ' + @file;
BACKUP DATABASE [McLabor] TO DISK = @file
    WITH COPY_ONLY, CHECKSUM, NOFORMAT, NOINIT, NAME = @name, STATS = 10;

PRINT N'Verifying (reads the whole file back, restores nothing)...';
RESTORE VERIFYONLY FROM DISK = @file WITH CHECKSUM;

RESTORE HEADERONLY FROM DISK = @file;   -- for the record: BackupFinishDate, BackupSize, HasBackupChecksums = 1
PRINT N'Backup file: ' + @file + N'  - keep a copy OUTSIDE this server (encrypted drive or administrators-only share).';
GO
SET NOEXEC OFF;
GO
