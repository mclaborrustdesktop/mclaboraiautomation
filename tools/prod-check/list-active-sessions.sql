-- READ-ONLY. Shows who is connected to the McLabor database right now. It changes nothing and disconnects nobody.
-- Run in SQL Server Management Studio as a SQL Server administrator, just before planned maintenance.
-- An empty list (or only your own Management Studio session) means it is safe to restart SQL Server.
SELECT
    s.session_id,
    s.host_name,                 -- the PC
    s.login_name,                -- who is signed in
    s.program_name,              -- e.g. "Microsoft Office" for Access
    s.status,                    -- running / sleeping
    s.last_request_end_time,     -- when this session last did something
    s.open_transaction_count     -- above 0 means unsaved work is in progress
FROM sys.dm_exec_sessions AS s
WHERE s.is_user_process = 1
  AND s.database_id = DB_ID(N'McLabor')
  AND s.session_id <> @@SPID
ORDER BY s.last_request_end_time DESC;
