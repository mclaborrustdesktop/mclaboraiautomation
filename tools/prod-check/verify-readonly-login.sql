-- READ-ONLY verification of the login's effective permissions. Run in SQL Server Management Studio as a sysadmin,
-- on the server where proposed-grants(-production).sql was run. It changes nothing: it impersonates the login,
-- asks the server what that login may do, and reverts. No business row is read.
USE [McLabor];
EXECUTE AS LOGIN = N'mclabor_web_read';
SELECT SUSER_SNAME() AS running_as, USER_NAME() AS database_user, DB_NAME() AS database_name;

-- 1. Server roles: every row must say 0.
SELECT r.role_name, IS_SRVROLEMEMBER(r.role_name) AS is_member FROM (VALUES ('sysadmin'), ('securityadmin'), ('serveradmin'), ('setupadmin'), ('processadmin'), ('diskadmin'), ('dbcreator'), ('bulkadmin')) r(role_name);

-- 2. Database roles: expect exactly one row, mclabor_web_readonly.
SELECT r.name AS database_role FROM sys.database_role_members rm JOIN sys.database_principals r ON r.principal_id = rm.role_principal_id
WHERE rm.member_principal_id = USER_ID();

-- 3. Effective database-level permissions: expect CONNECT only.
SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE') ORDER BY permission_name;

-- 4. Server-level: expect CONNECT SQL only (VIEW ANY DATABASE must be absent).
SELECT permission_name FROM fn_my_permissions(NULL, 'SERVER') ORDER BY permission_name;

-- 5. Write rights on ANY table or view of the database: expect 0 rows.
SELECT s.name + '.' + o.name AS object_name, p.permission_name
FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
CROSS APPLY (SELECT 'INSERT' AS permission_name UNION ALL SELECT 'UPDATE' UNION ALL SELECT 'DELETE' UNION ALL SELECT 'ALTER' UNION ALL SELECT 'REFERENCES' UNION ALL SELECT 'CONTROL') p
WHERE o.type IN ('U', 'V') AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', p.permission_name) = 1;

-- 6. Executable procedures and functions (write-capable or not): expect 0.
SELECT COUNT(*) AS executable_routines FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('P', 'PC', 'FN', 'IF', 'TF', 'FS', 'FT', 'X') AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'EXECUTE') = 1;

-- 7. Readable columns across the 33 approved tables: expect 288.
SELECT COUNT(*) AS readable_approved_columns FROM sys.columns c JOIN sys.objects o ON o.object_id = c.object_id
WHERE o.name IN (N'tblCustomer', N'tblCustomerContacts', N'tblCustomerNotes', N'tblEmployee', N'tblEmployeeB', N'tblEmployeeLicenses', N'tblEmployeeNotes', N'tblFeature', N'tblOfficeStaff', N'tblOfficeStaffActivity', N'tblOfficeStaffPermission', N'tblProject', N'tblPullDownContractWith_PayrollCo', N'tblPullDownCustStatus', N'tblPullDownCustomerContactTitles', N'tblPullDownCustomerTypes', N'tblPullDownDivisions', N'tblPullDownEmployeeNoteTypes', N'tblPullDownEmployeeStatus', N'tblPullDownExperience', N'tblPullDownLicenseTypes', N'tblPullDownPayrollCoOnSite', N'tblPullDownProjStatus', N'tblPullDownQualifications', N'tblPullDownSalesStatus', N'tblPullDownSalesman', N'tblPullDownStateCities', N'tblPullDownStates', N'tblPullDownStatusFlag', N'tblPullDownTrade', N'tblPullDownWCC', N'tblPullDownYearsInTrade', N'tblTracking') AND HAS_PERMS_BY_NAME('dbo.' + QUOTENAME(o.name), 'OBJECT', 'SELECT', c.name, 'COLUMN') = 1;

-- 8. Sensitive columns: every row must say 0.
SELECT col.table_name + '.' + col.column_name AS sensitive_column, HAS_PERMS_BY_NAME('dbo.' + QUOTENAME(col.table_name), 'OBJECT', 'SELECT', col.column_name, 'COLUMN') AS readable
FROM (VALUES (N'tblEmployee', N'BankAccountActionID'), (N'tblEmployee', N'BankAccountNumber'), (N'tblEmployee', N'BankAccountTypeID'), (N'tblEmployee', N'BankName'), (N'tblEmployee', N'BankRoutingNumber'), (N'tblEmployee', N'Citizenship'), (N'tblEmployee', N'Dependents'), (N'tblEmployee', N'EmCountryOfBirth'), (N'tblEmployee', N'EmDOB'), (N'tblEmployee', N'EmI9Notes'), (N'tblEmployee', N'EmRaceID'), (N'tblEmployee', N'EmSex'), (N'tblEmployee', N'EmW4Notes'), (N'tblEmployee', N'I9Complete'), (N'tblEmployee', N'SSNum'), (N'tblEmployee', N'USCitizen'), (N'tblOfficeStaff', N'OfficeStaffPassword')) col(table_name, column_name);

-- 9. Tables outside the approved list that this login can read: expect 0 rows.
SELECT s.name + '.' + o.name AS readable_unapproved FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('U', 'V') AND o.name NOT IN (N'tblCustomer', N'tblCustomerContacts', N'tblCustomerNotes', N'tblEmployee', N'tblEmployeeB', N'tblEmployeeLicenses', N'tblEmployeeNotes', N'tblFeature', N'tblOfficeStaff', N'tblOfficeStaffActivity', N'tblOfficeStaffPermission', N'tblProject', N'tblPullDownContractWith_PayrollCo', N'tblPullDownCustStatus', N'tblPullDownCustomerContactTitles', N'tblPullDownCustomerTypes', N'tblPullDownDivisions', N'tblPullDownEmployeeNoteTypes', N'tblPullDownEmployeeStatus', N'tblPullDownExperience', N'tblPullDownLicenseTypes', N'tblPullDownPayrollCoOnSite', N'tblPullDownProjStatus', N'tblPullDownQualifications', N'tblPullDownSalesStatus', N'tblPullDownSalesman', N'tblPullDownStateCities', N'tblPullDownStates', N'tblPullDownStatusFlag', N'tblPullDownTrade', N'tblPullDownWCC', N'tblPullDownYearsInTrade', N'tblTracking')
  AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'SELECT') = 1;

-- 10. Other databases visible to this login: expect only master, tempdb and McLabor.
SELECT name AS visible_database FROM sys.databases ORDER BY name;
REVERT;
