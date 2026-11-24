-- PROPOSAL - NOT RUN. Removes ONLY the temporary test copy created by script 2.
-- The name is fixed. This file cannot remove the McLabor database.

-- SAFETY: this script is for the STAGING copy only. It stops on any other server (for example LIVE-HOST).
IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\SQLEXPRESS'
BEGIN
    RAISERROR('Wrong server. This script only runs on DEV-PC\SQLEXPRESS (the restored copy). Nothing was done.', 16, 1);
    SET NOEXEC ON;  -- skips every remaining step of this script
END
GO

IF DB_ID(N'McLabor_RestoreTest') IS NULL
BEGIN
    PRINT N'McLabor_RestoreTest does not exist. Nothing to remove.';
    RETURN;
END

ALTER DATABASE [McLabor_RestoreTest] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
DROP DATABASE [McLabor_RestoreTest];
PRINT N'McLabor_RestoreTest removed. McLabor was not touched.';
GO

SET NOEXEC OFF;
GO
