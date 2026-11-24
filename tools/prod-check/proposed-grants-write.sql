-- PROPOSAL ONLY, for a LATER stage (docs/production/16-add-edit-plan.md). Nothing in this file has been run and it must
-- not be run before: (1) the read-only website has been in everyday use, (2) the owner has approved Add/Edit in writing
-- for a named environment and scope, (3) a fresh restore-tested backup exists. Rehearse on the restored copy (DEV-PC)
-- with STAGING_WRITES_ENABLED first; the server guard below is set to the COPY for that reason.
--
-- What it does: creates a SECOND login, mclabor_web_write, that may INSERT and UPDATE exactly the columns the website's
-- forms save, plus read the same 288 columns as the read-only login. It may NOT delete from the master tables, may not
-- touch the restricted columns (SSN, bank, DOB, citizenship, I-9, staff passwords), cannot run procedures and cannot
-- change the schema. The read-only login stays in use for everything that only reads.
-- Safe to run twice: every step checks whether it was already done.

USE [master];
IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\SQLEXPRESS'
BEGIN
    RAISERROR('This copy of the script is for the restored copy on DEV-PC\SQLEXPRESS (rehearsal). Nothing was created.', 16, 1);
    SET NOEXEC ON;
END
DECLARE @password nvarchar(128) = N'<<TYPE-A-LONG-PASSWORD-HERE>>';
IF @password LIKE N'%TYPE-A-LONG-PASSWORD%' OR LEN(@password) < 16
BEGIN
    RAISERROR('Replace the password placeholder with your own password of 16 or more characters. Nothing was created.', 16, 1);
    SET NOEXEC ON;
END
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'mclabor_web_write')
BEGIN
    DECLARE @sql nvarchar(max) = N'CREATE LOGIN [mclabor_web_write] WITH PASSWORD = ' + QUOTENAME(@password, '''')
        + N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = [McLabor]';
    EXEC (@sql);
END
GO
USE [McLabor];
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'mclabor_web_write')
    CREATE USER [mclabor_web_write] FOR LOGIN [mclabor_web_write];
-- it reads what the read-only role reads (the role must already exist: proposed-grants.sql)
IF IS_ROLEMEMBER(N'mclabor_web_readonly', N'mclabor_web_write') = 0
    ALTER ROLE [mclabor_web_readonly] ADD MEMBER [mclabor_web_write];
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'mclabor_web_writer' AND type = 'R')
    CREATE ROLE [mclabor_web_writer];
IF IS_ROLEMEMBER(N'mclabor_web_writer', N'mclabor_web_write') = 0
    ALTER ROLE [mclabor_web_writer] ADD MEMBER [mclabor_web_write];
GO
-- Columns the website's Add/Edit forms save (the "direct" fields reported by `python -m app.prodverify`), plus the
-- row-level entry stamps. Derived fields (years in trade, will-travel, site city/state) are NOT here until their write
-- mapping exists (16-add-edit-plan.md, step 3). Notes tables: INSERT only (append), no UPDATE.
GRANT INSERT, UPDATE ON dbo.[tblEmployee] ([EmFirstName], [EmLastName], [EmMiddle], [EmStreet], [EmStateCityID], [EmCity], [EmState], [EmZip], [EmHomePhone], [EmMobilePhone], [EmEmail],
    [EmEmployeeStatusID], [EmQualificationID], [EmTradeID], [SubTrade1ID], [SubTrade2ID], [EmExperienceID], [EmLicenseNum], [EmLicenseDateExpires], [EmLicensedIn], [OSHA10], [BaseSalary],
    [EmHowReferredID], [EmReferredBy], [ReferrerEmployeeID], [EmContractWith_PayrollCoID], [JobApplComplete], [EmApplComplete], [Recruiter], [PostEmployeeAsAvailable], [EmployeeNoCommunication],
    [EmAdminNotes], [EmSalesNotes], [EmEntryUserName], [EmEntryTimestamp], [EmployeeDuplicate]) TO [mclabor_web_writer];
GRANT INSERT, UPDATE, DELETE ON dbo.[tblEmployeeLicenses] TO [mclabor_web_writer];          -- the licence list is replaced as a whole when a record is saved
GRANT INSERT ON dbo.[tblEmployeeNotes] ([EmployeeID], [EmployeeNote], [EmployeeNoteUserName], [EmployeeNoteTimestamp], [EmployeeNoteTypeID], [EmployeeNoteCustomerID]) TO [mclabor_web_writer];
GRANT INSERT, UPDATE ON dbo.[tblCustomer] ([CustBusName], [Street], [StateCityID], [City], [State], [Zip], [Phone], [CustEmail], [CustFaxNum], [CustWebSiteHLink], [CustStatusID], [CustomerTypeID],
    [SalesmanID], [SalesStatusID], [CustContractWith_PayrollCoID], [ContractOnFile], [ContractDate], [CreditLimit], [RevenuePerYear], [LaborRateAFrom], [LaborRateATo], [LaborRateBFrom], [LaborRateBTo],
    [BillRateOTMultiplier], [Industry], [EmployeeSize], [CustomerDescription], [CustomerNote], [InvoiceNote], [CollectionsNote], [OnHold], [FutureSales], [FutureCall], [CustomerLicenseNumber],
    [CustEntryUserName], [CustEntryTimestamp]) TO [mclabor_web_writer];
GRANT INSERT, UPDATE, DELETE ON dbo.[tblCustomerContacts] TO [mclabor_web_writer];
GRANT INSERT ON dbo.[tblCustomerNotes] ([CustomerID], [CustomerNote], [CustomerNoteUserName], [CustomerNoteTimestamp], [CustomerNoteActive]) TO [mclabor_web_writer];
GRANT INSERT, UPDATE ON dbo.[tblProject] ([CustomerID], [SiteName], [SiteStreet], [SiteStateCityID], [SiteZip], [StartDate], [EndDate], [ProjStatusID], [ProjectWCCID], [ProjNote], [ProjOfficeNote],
    [JobNote], [ProjStartTime], [OCIPJob], [RateJob], [ShiftDifferential], [JobBeingManned], [GCOnSite], [ARateQty], [BRateQty], [CRateQty], [NumberOfEmployees], [ContractAmount],
    [ContractTotalPayments], [ContractBalanceOwed], [CustomerContact], [CustomerPhone], [CustomerEmail], [ParentProjectID], [ProjectEntryUserName], [ProjectEntryTimestamp]) TO [mclabor_web_writer];
GRANT INSERT, UPDATE ON dbo.[tblTracking] ([CustomerID], [EmployeeID], [ProjectID], [AssignWeek], [AssignYear], [WeekEndingDate], [PayRate], [BillRate], [OTPayRate], [BillRateOT], [SatHours],
    [SunHours], [MonHours], [TueHours], [WedHours], [ThuHours], [FriHours], [TotalHours], [RegularHours], [OvertimeHours], [InvoiceAmount], [EmGrossPayroll], [CalcProfitMargin], [Grade],
    [DirVerified], [Placeholder], [PayrollCoOnSiteID], [HoursNote], [AssignmentUserName], [AssignmentTimestamp]) TO [mclabor_web_writer];
GRANT INSERT ON dbo.[tblOfficeStaffActivity] ([OfficeStaffID], [OfficeStaffActivityObjectName], [OfficeStaffActivityObjectID], [OfficeStaffActivityTimestampStart]) TO [mclabor_web_writer];
-- Deliberately NOT granted: DELETE on tblEmployee, tblCustomer, tblProject, tblTracking (the website deactivates or
-- the office uses Access); anything on tblOfficeStaff / tblOfficeStaffPermission (users are managed in Access);
-- any restricted column; any lookup table.
GO
-- Check (read-only): expect only INSERT / UPDATE / DELETE rows on the tables above, none on the restricted columns.
SELECT OBJECT_NAME(major_id) AS [table], permission_name, COUNT(*) AS columns_or_table
FROM sys.database_permissions WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'mclabor_web_writer') AND class = 1
GROUP BY OBJECT_NAME(major_id), permission_name ORDER BY 1, 2;
GO
SET NOEXEC OFF;
GO
-- TO UNDO: USE [McLabor]; DROP USER [mclabor_web_write]; DROP ROLE [mclabor_web_writer]; USE [master]; DROP LOGIN [mclabor_web_write];
