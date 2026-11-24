-- PROPOSAL ONLY. Nothing in this file has been run. Do not run it without the owner's approval.
-- For whoever administers the McLabor SQL Server (a sysadmin), in SQL Server Management Studio.
--
-- What it does: creates ONE login that can only read approved columns of the McLabor database.
--   33 tables, 288 columns, read access only. It cannot change, add or remove anything,
--   cannot run stored procedures, and cannot see any other table or database.
-- What it does not do: it creates no tables, changes no data, and changes no server setting.
--   This server already allows SQL logins (mixed mode), so no restart is needed.
-- Never readable by this login: tblEmployee: BankAccountActionID, BankAccountNumber, BankAccountTypeID, BankName, BankRoutingNumber, Citizenship, Dependents, EmCountryOfBirth, EmDOB, EmI9Notes, EmRaceID, EmSex, EmW4Notes, I9Complete, SSNum, USCitizen; tblOfficeStaff: OfficeStaffPassword
-- Safe to run twice: every step checks whether it was already done.

-- STEP 1 - the login. Replace the password placeholder with a long password (16+ characters) typed here by you.
--          Do not e-mail it or paste it into a chat. You will type it once more when the web app is configured.
USE [master];
-- SAFETY: this copy of the script is for the STAGING database on DEV-PC only. It stops on any other server.
IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\SQLEXPRESS'
BEGIN
    RAISERROR('Wrong server. This script only runs on DEV-PC\SQLEXPRESS (the restored copy). Nothing was created.', 16, 1);
    SET NOEXEC ON;
END
DECLARE @password nvarchar(128) = N'<<TYPE-A-LONG-PASSWORD-HERE>>';
IF @password LIKE N'%TYPE-A-LONG-PASSWORD%' OR LEN(@password) < 16
BEGIN
    RAISERROR('Replace the password placeholder with your own password of 16 or more characters. Nothing was created.', 16, 1);
    SET NOEXEC ON;  -- skips every remaining step of this script
END
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'mclabor_web_read')
BEGIN
    DECLARE @sql nvarchar(max) = N'CREATE LOGIN [mclabor_web_read] WITH PASSWORD = ' + QUOTENAME(@password, '''')
        + N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = [McLabor]';
    EXEC (@sql);
END
GO
-- (Alternative instead of STEP 1, no password to manage: a dedicated local Windows account that runs the web app.
--  CREATE LOGIN [DEV-PC\mclabor_web] FROM WINDOWS WITH DEFAULT_DATABASE = [McLabor];
--  then use [DEV-PC\mclabor_web] in place of the login name in STEP 2. That Windows account must be created first.)

-- STEP 2 - a database user for that login, and a role that holds the read permissions.
USE [McLabor];
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'mclabor_web_read')
    CREATE USER [mclabor_web_read] FOR LOGIN [mclabor_web_read];
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'mclabor_web_readonly' AND type = 'R')
    CREATE ROLE [mclabor_web_readonly];
IF IS_ROLEMEMBER(N'mclabor_web_readonly', N'mclabor_web_read') = 0
    ALTER ROLE [mclabor_web_readonly] ADD MEMBER [mclabor_web_read];
GO
-- Do NOT add this user to db_datareader, db_datawriter or db_owner.

-- STEP 3 - read access, column by column.
GRANT SELECT ON dbo.[tblCustomer] ([BillRateOTMultiplier], [City], [CollectionsNote], [ContractDate], [ContractOnFile], [CreditLimit], [CustBusName], [CustContractWith_PayrollCoID], [CustEmail], [CustEntryTimestamp], [CustEntryUserName], [CustFaxNum], [CustStatusID], [CustWebSiteHLink], [CustomerDescription], [CustomerID], [CustomerLicenseNumber], [CustomerNote], [CustomerTypeID], [EmployeeSize], [FutureCall], [FutureSales], [Industry], [InvoiceNote], [LaborRateAFrom], [LaborRateATo], [LaborRateBFrom], [LaborRateBTo], [OnHold], [Phone], [RevenuePerYear], [SalesStatusID], [SalesmanID], [State], [StateCityID], [Street], [Zip]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblCustomerContacts] ([CustomerContactCell], [CustomerContactEmail], [CustomerContactFName], [CustomerContactID], [CustomerContactLName], [CustomerContactNotes], [CustomerContactOfficePhone], [CustomerContactPriority], [CustomerContactTimestamp], [CustomerContactTitleID], [CustomerContactUserName], [CustomerID]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblCustomerNotes] ([CustomerID], [CustomerNote], [CustomerNoteActive], [CustomerNoteID], [CustomerNoteTimestamp], [CustomerNoteUserName]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblEmployee] ([BaseSalary], [EmAdminNotes], [EmApplComplete], [EmCity], [EmContractWith_PayrollCoID], [EmEmail], [EmEmployeeStatusID], [EmEntryTimestamp], [EmEntryUserName], [EmExperienceID], [EmFirstName], [EmHomePhone], [EmHowReferredID], [EmLastName], [EmLicenseDateExpires], [EmLicenseNum], [EmLicensedIn], [EmMiddle], [EmMobilePhone], [EmQualificationID], [EmReferredBy], [EmSalesNotes], [EmState], [EmStateCityID], [EmStreet], [EmTradeID], [EmZip], [EmployeeDuplicate], [EmployeeID], [EmployeeNoCommunication], [JobApplComplete], [OSHA10], [PostEmployeeAsAvailable], [Recruiter], [ReferrerEmployeeID], [SubTrade1ID], [SubTrade2ID], [YearsInTradeID]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblEmployeeB] ([EmployeeID], [WillTravel]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblEmployeeLicenses] ([EmployeeID], [EmployeeLicenseCopyOnFile], [EmployeeLicenseExpDate], [EmployeeLicenseID], [EmployeeLicenseNotes], [EmployeeLicenseNumber], [EmployeeLicenseStateID], [EmployeeLicenseTradeID], [EmployeeLicenseTypeID]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblEmployeeNotes] ([EmployeeID], [EmployeeNote], [EmployeeNoteCustomerID], [EmployeeNoteID], [EmployeeNoteTimestamp], [EmployeeNoteTypeID], [EmployeeNoteUserName]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblFeature] ([ControlName], [FeatureActive], [FeatureDescription], [FeatureID], [FeatureSort], [FeatureTitle], [ObjectName]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblOfficeStaff] ([Initials], [OfficeStaffActive], [OfficeStaffCanDelete], [OfficeStaffEmail], [OfficeStaffEmployeeResearch], [OfficeStaffFirstName], [OfficeStaffFullName], [OfficeStaffHideHours], [OfficeStaffID], [OfficeStaffLastName], [OfficeStaffTitle], [OfficeStaffTrackingReportEmailReceive], [Profile]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblOfficeStaffActivity] ([OfficeStaffActivityID], [OfficeStaffActivityObjectID], [OfficeStaffActivityObjectName], [OfficeStaffActivityTimestampStart], [OfficeStaffID]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblOfficeStaffPermission] ([FeatureID], [OfficeStaffID], [OfficeStaffPermissionID]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblProject] ([ARateQty], [BRateQty], [CRateQty], [ContractAmount], [ContractBalanceOwed], [ContractTotalPayments], [CustomerContact], [CustomerEmail], [CustomerID], [CustomerPhone], [EndDate], [GCOnSite], [JobBeingManned], [JobNote], [NumberOfEmployees], [OCIPJob], [ParentProjectID], [ProjNote], [ProjOfficeNote], [ProjStartTime], [ProjStatusID], [ProjectEntryTimestamp], [ProjectEntryUserName], [ProjectID], [ProjectWCCID], [RateJob], [ShiftDifferential], [SiteName], [SiteStateCityID], [SiteStreet], [SiteZip], [StartDate]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownContractWith_PayrollCo] ([PullDownContractWith_PayrollCoID], [PullDownContractWith_PayrollCoInitials], [PullDownContractWith_PayrollCoName], [PullDownContractWith_PayrollCoSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownCustStatus] ([PulldownCustStatus], [PulldownCustStatusID], [PulldownCustStatusSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownCustomerContactTitles] ([PullDownCustomerContactTitle], [PullDownCustomerContactTitleID], [PullDownCustomerContactTitleSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownCustomerTypes] ([PullDownCustomerType], [PullDownCustomerTypeDivisionID], [PullDownCustomerTypeID], [PullDownCustomerTypeSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownDivisions] ([PullDownDivision], [PullDownDivisionActive], [PullDownDivisionID], [PullDownDivisionSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownEmployeeNoteTypes] ([PullDownEmployeeNoteType], [PullDownEmployeeNoteTypeID], [PullDownEmployeeNoteTypeSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownEmployeeStatus] ([PullDownEmployeeStatus], [PullDownEmployeeStatusID], [PullDownEmployeeStatusSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownExperience] ([PullDownExperience], [PullDownExperienceID], [PullDownExperienceSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownLicenseTypes] ([PullDownLicenseType], [PullDownLicenseTypeActive], [PullDownLicenseTypeID], [PullDownLicenseTypeSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownPayrollCoOnSite] ([PullDownPayrollCoOnSiteActive], [PullDownPayrollCoOnSiteID], [PullDownPayrollCoOnSiteInitials], [PullDownPayrollCoOnSiteName], [PullDownPayrollCoOnSiteSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownProjStatus] ([PullDownProjStatus], [PullDownProjStatusID], [PullDownProjStatusSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownQualifications] ([PullDownQualification], [PullDownQualificationDivisionID], [PullDownQualificationID], [PullDownQualificationSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownSalesStatus] ([PullDownSalesStatus], [PullDownSalesStatusID], [PullDownSalesStatusSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownSalesman] ([OfficeStaffID], [PullDownSalesmanActive], [PullDownSalesmanCell], [PullDownSalesmanEmail], [PullDownSalesmanFName], [PullDownSalesmanID], [PullDownSalesmanLName], [PullDownSalesmanSort], [PullDownSalesmanTitle]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownStateCities] ([City], [PullDownStateCityActive], [PullDownStateCityID], [PullDownStateCitySort], [StateID]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownStates] ([PullDownState], [PullDownStateID], [PullDownStateName], [PullDownStateSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownStatusFlag] ([PullDownStatusFlag], [PullDownStatusFlagDesc], [PullDownStatusFlagID], [PullDownStatusFlagSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownTrade] ([PullDownTrade], [PullDownTradeDivisionID], [PullDownTradeID], [PullDownTradeSort], [PullDownTradeSwitch]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownWCC] ([PullDownWCC], [PullDownWCCActive], [PullDownWCCDesc], [PullDownWCCDivisionID], [PullDownWCCID], [PullDownWCCSort]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblPullDownYearsInTrade] ([PullDownYearsInTrade], [PullDownYearsInTradeID]) TO [mclabor_web_readonly];
GRANT SELECT ON dbo.[tblTracking] ([AssignWeek], [AssignYear], [AssignmentTimestamp], [AssignmentUserName], [BillRate], [BillRateOT], [CalcProfitMargin], [CustomerID], [DirVerified], [DirectionsSentEmail], [DirectionsSentText], [EmGrossPayroll], [EmployeeID], [FriHours], [Grade], [HoursNote], [InvoiceAmount], [MonHours], [MonStatusFlagID], [OTPayRate], [OvertimeHours], [PayRate], [PayrollCoOnSiteID], [PayrollInfoSent], [Placeholder], [ProjectID], [RegularHours], [SatHours], [SunHours], [ThuHours], [TotalHours], [TrackingID], [TueHours], [WCC], [WedHours], [WeekEndingDate]) TO [mclabor_web_readonly];
GO

-- STEP 4 - check the result (read-only queries).
-- Expect 288 column permissions on 33 tables, all SELECT:
SELECT COUNT(*) AS column_permissions, COUNT(DISTINCT major_id) AS tables, MIN(permission_name) AS permission, MAX(permission_name) AS permission_check
FROM sys.database_permissions WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'mclabor_web_readonly') AND class = 1;
-- Expect 0 rows (the user must not be in any built-in role):
SELECT r.name AS unexpected_role FROM sys.database_role_members rm JOIN sys.database_principals r ON r.principal_id = rm.role_principal_id
WHERE rm.member_principal_id = DATABASE_PRINCIPAL_ID(N'mclabor_web_read') AND r.name <> N'mclabor_web_readonly';
GO

SET NOEXEC OFF;
GO

-- TO UNDO EVERYTHING:
-- USE [McLabor]; DROP USER [mclabor_web_read]; DROP ROLE [mclabor_web_readonly];
-- USE [master];  DROP LOGIN [mclabor_web_read];
