-- READ-ONLY. For a SQL Server administrator, in SQL Server Management Studio, connected to the McLabor database.
-- Question: where are the employees' phone numbers, addresses and e-mails kept?
-- On the restored copy (DEV-PC, data of 2026-11-13) the website's approved columns EmStreet, EmStateCityID, EmCity,
-- EmState, EmZip, EmHomePhone, EmMobilePhone and EmEmail are NULL for ALL 178,993 employees, while first/last name,
-- trade and entry stamps are filled. The website's login may not read the other address/phone columns, so an
-- administrator has to run this. It returns COUNTS ONLY - no name, number or address - and changes nothing.
-- Run it on the copy first; on the live server (once confirmed) only with the owner's approval.

-- 1. How many employees have SOMETHING in each candidate column (counts, not values)
SELECT
    COUNT(EmployeeID)                                                             AS employees,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmMobilePhone)), '') IS NOT NULL THEN 1 ELSE 0 END) AS EmMobilePhone,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmHomePhone)), '')   IS NOT NULL THEN 1 ELSE 0 END) AS EmHomePhone,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmSmartPhone)), '')  IS NOT NULL THEN 1 ELSE 0 END) AS EmSmartPhone,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(TextMsgAddress)), '') IS NOT NULL THEN 1 ELSE 0 END) AS TextMsgAddress,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmEmail)), '')       IS NOT NULL THEN 1 ELSE 0 END) AS EmEmail,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmStreet)), '')      IS NOT NULL THEN 1 ELSE 0 END) AS EmStreet,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmAddress)), '')     IS NOT NULL THEN 1 ELSE 0 END) AS EmAddress,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmCity)), '')        IS NOT NULL THEN 1 ELSE 0 END) AS EmCity,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmState)), '')       IS NOT NULL THEN 1 ELSE 0 END) AS EmState,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmZip)), '')         IS NOT NULL THEN 1 ELSE 0 END) AS EmZip,
    SUM(CASE WHEN EmStateCityID IS NOT NULL THEN 1 ELSE 0 END)                           AS EmStateCityID,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmMailStreet)), '')  IS NOT NULL THEN 1 ELSE 0 END) AS EmMailStreet,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmMailCity)), '')    IS NOT NULL THEN 1 ELSE 0 END) AS EmMailCity,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmMailAddress)), '') IS NOT NULL THEN 1 ELSE 0 END) AS EmMailAddress,
    SUM(CASE WHEN EmMobilePhoneTimestamp IS NOT NULL THEN 1 ELSE 0 END)                  AS EmMobilePhoneTimestamp_set
FROM dbo.tblEmployee;

-- 2. The extra phone / e-mail columns in the extension table
SELECT
    COUNT(EmployeeBID) AS rows_in_tblEmployeeB,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmMobilePhone2)), '') IS NOT NULL THEN 1 ELSE 0 END) AS EmMobilePhone2,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmHomePhone2)), '')   IS NOT NULL THEN 1 ELSE 0 END) AS EmHomePhone2,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(EmEmail2)), '')       IS NOT NULL THEN 1 ELSE 0 END) AS EmEmail2
FROM dbo.tblEmployeeB;

-- 3. If the phone columns are empty but a "mobile phone changed by / on" stamp is set, the values were removed after
--    they had been entered (a scrubbed copy). If the stamps are NULL as well, they were never in this database.
SELECT TOP 5 YEAR(EmMobilePhoneTimestamp) AS year_set, COUNT(EmployeeID) AS employees
FROM dbo.tblEmployee WHERE EmMobilePhoneTimestamp IS NOT NULL GROUP BY YEAR(EmMobilePhoneTimestamp) ORDER BY 1 DESC;
