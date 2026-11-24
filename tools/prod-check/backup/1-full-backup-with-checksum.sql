-- PROPOSAL - NOT RUN. Needs the client's approval. Run in SQL Server Management Studio as a SQL Server administrator.
--
-- Makes one full backup of the McLabor database on the server you are connected to, and checks it.
-- Written and reviewed for the RESTORED COPY on DEV-PC\SQLEXPRESS (staging). Check the server name in the
-- SSMS title bar before pressing Execute.
-- It only READS the database. Nobody is disconnected, nothing is restarted, no record is changed.
--   COPY_ONLY  = does not disturb any other backup routine.
--   CHECKSUM   = SQL Server re-checks every page as it reads it and stores a checksum for the whole backup,
--                so damage is caught now instead of on the day the backup is needed.
-- Expected size: about 1.7 GB (the database is 2.26 GB allocated; Express Edition cannot compress backups).
-- Expected time: a few minutes. Free space on C: at the time of writing: 848 GB.

-- SAFETY: this script is for the STAGING copy only. It stops on any other server (for example LIVE-HOST).
IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\SQLEXPRESS'
BEGIN
    RAISERROR('Wrong server. This script only runs on DEV-PC\SQLEXPRESS (the restored copy). Nothing was done.', 16, 1);
    SET NOEXEC ON;  -- skips every remaining step of this script
END
GO

DECLARE @folder nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260));  -- SQL Server's own backup folder (administrators only)
DECLARE @file   nvarchar(400) = @folder + N'\McLabor_DEV-PC_' + FORMAT(SYSDATETIME(), 'yyyy-MM-dd_HHmmss') + N'_full_copyonly.bak';
DECLARE @name   nvarchar(128) = N'McLabor full copy-only backup ' + CONVERT(nvarchar(16), SYSDATETIME(), 120);

PRINT N'Backing up to: ' + @file;
BACKUP DATABASE [McLabor] TO DISK = @file
    WITH COPY_ONLY, CHECKSUM, NOFORMAT, NOINIT, NAME = @name, STATS = 10;

-- Read the whole backup file back and check every checksum. Restores nothing.
PRINT N'Verifying...';
RESTORE VERIFYONLY FROM DISK = @file WITH CHECKSUM;

-- What is in the file (for the record).
RESTORE HEADERONLY FROM DISK = @file;
PRINT N'Backup file: ' + @file;
GO

SET NOEXEC OFF;
GO
