-- PROPOSAL ONLY. Nothing in this file has been run. Needs the owner's approval, a restore-tested backup, and a
-- SQL Server administrator. Rehearse on the restored copy (DEV-PC) first.
--
-- Why: a search for a word in a name, address, e-mail or note ('%word%') has to compare every row of the table,
-- 10 columns each, and no ordinary index can help. Measured on the restored copy on 2026-11-23 after the application
-- changes: customers "electric" 1.6 s, "harbor electric" 3.2 s, employees "smith" 0.6 s, "john smith" 1.0 s. With
-- 30 people searching, SQL Server Express's 4 processor cores are the limit. A FULL-TEXT index keeps a word list
-- for those columns, so a word search becomes a lookup in milliseconds.
--
-- What changes for the user (this is a change in behaviour, so the owner must accept it):
--   * a full-text search finds WORDS and word prefixes ("electric" finds "Electric", "Electrical", "electricians"),
--     not fragments inside a word ("lectri" finds nothing). Phone-digit searches stay as they are.
--   * new or changed rows appear in the word list within seconds (automatic population), not instantly.
--
-- Requirement: full-text search must be installed on the instance. SQL Server 2019 EXPRESS (plain) does NOT include
-- it; "Express with Advanced Services" does. Check first, read-only:
--     SELECT SERVERPROPERTY('IsFullTextInstalled');      -- 1 = installed, 0 = not installed
-- If it returns 0, installing it means re-running SQL Server setup to add the feature (downtime, a server change)
-- or moving to a different edition - a separate decision and not part of this proposal.
-- The restored copy on DEV-PC reported 0 on 2026-11-23 (tools/prod-check/reports): the feature is NOT installed there.
--
-- Application side: the website keeps its LIKE searches until a setting (SEARCH_FULLTEXT=true, to be written)
-- switches the keyword predicate to CONTAINS(...). The result ranking and every filter stay as they are.

USE [McLabor];
IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\SQLEXPRESS'
BEGIN
    RAISERROR('This copy of the script is for the restored copy on DEV-PC\SQLEXPRESS only. Nothing was created.', 16, 1);
    SET NOEXEC ON;
END
IF CAST(SERVERPROPERTY('IsFullTextInstalled') AS int) <> 1
BEGIN
    RAISERROR('Full-text search is not installed on this instance. Nothing was created.', 16, 1);
    SET NOEXEC ON;
END

IF NOT EXISTS (SELECT 1 FROM sys.fulltext_catalogs WHERE name = N'McLaborSearch')
    CREATE FULLTEXT CATALOG McLaborSearch WITH ACCENT_SENSITIVITY = OFF;

-- Full-text indexes need a unique, single-column, non-nullable index: the primary keys qualify.
IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID(N'dbo.tblCustomer'))
    CREATE FULLTEXT INDEX ON dbo.tblCustomer
        (CustBusName, Street, City, Zip, CustEmail, Industry, CustomerDescription, CustomerNote, InvoiceNote)
        KEY INDEX [tblCustomer$PrimaryKey] ON McLaborSearch WITH CHANGE_TRACKING AUTO;

IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID(N'dbo.tblCustomerContacts'))
    CREATE FULLTEXT INDEX ON dbo.tblCustomerContacts (CustomerContactFName, CustomerContactLName)
        KEY INDEX [tblCustomerContacts$PrimaryKey] ON McLaborSearch WITH CHANGE_TRACKING AUTO;

IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID(N'dbo.tblEmployee'))
    CREATE FULLTEXT INDEX ON dbo.tblEmployee
        (EmFirstName, EmLastName, EmCity, EmZip, EmEmail, EmLicensedIn, EmAdminNotes, EmSalesNotes)
        KEY INDEX [tblEmployee$PrimaryKey] ON McLaborSearch WITH CHANGE_TRACKING AUTO;

IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID(N'dbo.tblProject'))
    CREATE FULLTEXT INDEX ON dbo.tblProject (SiteName, SiteStreet, SiteZip, ProjNote, JobNote, ProjOfficeNote, CustomerContact)
        KEY INDEX [tblProject$PrimaryKey] ON McLaborSearch WITH CHANGE_TRACKING AUTO;

SET NOEXEC OFF;
GO
-- Check (read-only): population status 0 = idle, i.e. finished.
-- SELECT OBJECT_NAME(object_id), FULLTEXTCATALOGPROPERTY('McLaborSearch', 'PopulateStatus') FROM sys.fulltext_indexes;
-- TO UNDO: DROP FULLTEXT INDEX ON dbo.<table>; for each table, then DROP FULLTEXT CATALOG McLaborSearch;
