-- READ-ONLY. Lists the indexes that exist today on the tables the website searches, and how large the tables are.
-- It changes nothing. Run in SQL Server Management Studio, connected to the McLabor database, and send back the
-- two result grids. They decide which (if any) of the suggested indexes in docs/search-performance.md are worth
-- proposing. No index is to be created without the owner's approval.
SELECT
    t.name                                             AS table_name,
    i.name                                             AS index_name,
    i.type_desc                                        AS kind,
    i.is_unique,
    i.is_primary_key,
    STUFF((SELECT ', ' + c.name
           FROM sys.index_columns ic JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
           WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 0
           ORDER BY ic.key_ordinal FOR XML PATH('')), 1, 2, '')   AS key_columns,
    STUFF((SELECT ', ' + c.name
           FROM sys.index_columns ic JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
           WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 1
           ORDER BY c.name FOR XML PATH('')), 1, 2, '')           AS included_columns
FROM sys.tables t
JOIN sys.indexes i ON i.object_id = t.object_id AND i.type > 0
WHERE t.name IN (N'tblEmployee', N'tblEmployeeB', N'tblEmployeeLicenses', N'tblCustomer', N'tblCustomerContacts', N'tblProject', N'tblTracking',
                 N'tblPullDownStateCities', N'tblPullDownTrade')
ORDER BY t.name, i.index_id;

SELECT
    t.name                                                        AS table_name,
    SUM(CASE WHEN p.index_id IN (0, 1) THEN p.row_count ELSE 0 END) AS row_count,
    CAST(SUM(p.reserved_page_count) * 8 / 1024.0 AS decimal(12, 1)) AS size_mb,
    (SELECT COUNT(*) FROM sys.columns c WHERE c.object_id = t.object_id) AS column_count
FROM sys.tables t
JOIN sys.dm_db_partition_stats p ON p.object_id = t.object_id
WHERE t.name IN (N'tblEmployee', N'tblEmployeeB', N'tblEmployeeLicenses', N'tblCustomer', N'tblCustomerContacts', N'tblProject', N'tblTracking')
GROUP BY t.name, t.object_id
ORDER BY size_mb DESC;
