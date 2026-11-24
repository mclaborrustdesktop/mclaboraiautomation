-- Word searches (ILIKE 'contains') served from trigram indexes: needs the pg_trgm contrib extension, which hosted
-- PostgreSQL (Railway, Azure, AWS) ships. Optional: the searches work without it, from sequential scans.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS "tx_employee_last" ON "tblEmployee" USING gin ("EmLastName" gin_trgm_ops);
CREATE INDEX IF NOT EXISTS "tx_employee_first" ON "tblEmployee" USING gin ("EmFirstName" gin_trgm_ops);
CREATE INDEX IF NOT EXISTS "tx_customer_name" ON "tblCustomer" USING gin ("CustBusName" gin_trgm_ops);
CREATE INDEX IF NOT EXISTS "tx_project_site" ON "tblProject" USING gin ("SiteName" gin_trgm_ops);
