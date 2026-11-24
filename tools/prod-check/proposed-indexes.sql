-- PROPOSAL ONLY. Nothing in this file has been run. Do not run it without the owner's approval and a fresh,
-- restore-tested backup. For a SQL Server administrator, first on the restored copy (DEV-PC), never on the live
-- server before the copy has shown the gain.
--
-- Why: measured on the restored copy on 2026-11-23 (docs/search-performance.md). After the application changes the
-- filtered lists are fast, but a few paths still read whole tables because the needed columns have no index:
--   * "licensed" filter: 0.5-0.9 s   (tblEmployeeLicenses has no index on EmployeeID; 45,000+ rows scanned)
--   * "last week worked", a job's crew, an employee's history: tblTracking scanned by EmployeeID / ProjectID
--   * the weekly grid and the dashboard: tblTracking scanned by WeekEndingDate
--   * customer status / type / sales-rep filters and the "active jobs" filter: tblCustomer and tblProject scanned
-- A word INSIDE a name or note ('%word%') does NOT benefit from these indexes - see proposed-fulltext.sql.
--
-- Cost: each index uses disk space and makes Access saves on that table slightly slower. Add them ONE AT A TIME,
-- measuring with tools\staging\search_timing.py before and after, and keep only the ones that help.
-- Every statement checks whether the index already exists, so the file is safe to run twice.

USE [McLabor];
IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\SQLEXPRESS'
BEGIN
    RAISERROR('This copy of the script is for the restored copy on DEV-PC\SQLEXPRESS only. Nothing was created.', 16, 1);
    SET NOEXEC ON;
END

-- 1. tblEmployeeLicenses by employee: the "licensed" filter and the license list on each employee record
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblEmployeeLicenses_EmployeeID' AND object_id = OBJECT_ID(N'dbo.tblEmployeeLicenses'))
    CREATE NONCLUSTERED INDEX IX_tblEmployeeLicenses_EmployeeID ON dbo.tblEmployeeLicenses (EmployeeID) INCLUDE (EmployeeLicenseExpDate);

-- 2. tblTracking by employee and week: "last week worked" on every employee list, an employee's history
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblTracking_EmployeeID_WeekEndingDate' AND object_id = OBJECT_ID(N'dbo.tblTracking'))
    CREATE NONCLUSTERED INDEX IX_tblTracking_EmployeeID_WeekEndingDate ON dbo.tblTracking (EmployeeID, WeekEndingDate);

-- 3. tblTracking by job: crew counts on the job list, a job's assignments
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblTracking_ProjectID' AND object_id = OBJECT_ID(N'dbo.tblTracking'))
    CREATE NONCLUSTERED INDEX IX_tblTracking_ProjectID ON dbo.tblTracking (ProjectID) INCLUDE (EmployeeID);

-- 4. tblTracking by week: the weekly grid, the dashboard's week totals
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblTracking_WeekEndingDate' AND object_id = OBJECT_ID(N'dbo.tblTracking'))
    CREATE NONCLUSTERED INDEX IX_tblTracking_WeekEndingDate ON dbo.tblTracking (WeekEndingDate) INCLUDE (EmployeeID, TotalHours, InvoiceAmount, EmGrossPayroll);

-- 5. tblProject by customer and status: jobs per customer, the "active jobs" filter, the dashboard
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblProject_CustomerID_ProjStatusID' AND object_id = OBJECT_ID(N'dbo.tblProject'))
    CREATE NONCLUSTERED INDEX IX_tblProject_CustomerID_ProjStatusID ON dbo.tblProject (CustomerID, ProjStatusID);

-- 6. tblCustomer filters: status, type, sales rep, location. Narrow indexes on a 249-column table.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblCustomer_CustStatusID' AND object_id = OBJECT_ID(N'dbo.tblCustomer'))
    CREATE NONCLUSTERED INDEX IX_tblCustomer_CustStatusID ON dbo.tblCustomer (CustStatusID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblCustomer_CustomerTypeID' AND object_id = OBJECT_ID(N'dbo.tblCustomer'))
    CREATE NONCLUSTERED INDEX IX_tblCustomer_CustomerTypeID ON dbo.tblCustomer (CustomerTypeID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblCustomer_SalesmanID' AND object_id = OBJECT_ID(N'dbo.tblCustomer'))
    CREATE NONCLUSTERED INDEX IX_tblCustomer_SalesmanID ON dbo.tblCustomer (SalesmanID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblCustomer_State_City' AND object_id = OBJECT_ID(N'dbo.tblCustomer'))
    CREATE NONCLUSTERED INDEX IX_tblCustomer_State_City ON dbo.tblCustomer (State, City);

-- 7. tblCustomerContacts by customer: the contact list on each customer record
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblCustomerContacts_CustomerID' AND object_id = OBJECT_ID(N'dbo.tblCustomerContacts'))
    CREATE NONCLUSTERED INDEX IX_tblCustomerContacts_CustomerID ON dbo.tblCustomerContacts (CustomerID);

-- 8. tblEmployee filters: trade, status, location. The name columns already have indexes.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblEmployee_EmTradeID' AND object_id = OBJECT_ID(N'dbo.tblEmployee'))
    CREATE NONCLUSTERED INDEX IX_tblEmployee_EmTradeID ON dbo.tblEmployee (EmTradeID) INCLUDE (EmployeeDuplicate);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblEmployee_EmEmployeeStatusID' AND object_id = OBJECT_ID(N'dbo.tblEmployee'))
    CREATE NONCLUSTERED INDEX IX_tblEmployee_EmEmployeeStatusID ON dbo.tblEmployee (EmEmployeeStatusID) INCLUDE (EmployeeDuplicate);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_tblEmployee_EmState_EmCity' AND object_id = OBJECT_ID(N'dbo.tblEmployee'))
    CREATE NONCLUSTERED INDEX IX_tblEmployee_EmState_EmCity ON dbo.tblEmployee (EmState, EmCity) INCLUDE (EmployeeDuplicate);

SET NOEXEC OFF;
GO
-- TO UNDO: DROP INDEX <name> ON dbo.<table>;  for each index above. Undo is immediate and loses nothing.
