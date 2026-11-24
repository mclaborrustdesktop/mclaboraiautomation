-- Business rules the website enforces, as database constraints (app/pgschema.py).
-- Apply AFTER the migrated data has been checked (a legacy row that breaks a rule would stop the ALTER). The
-- website validates the same rules itself, so the application works with or without these.

ALTER TABLE "tblTracking" ADD CONSTRAINT "ck_tracking_hours" CHECK (("SatHours" IS NULL OR "SatHours" BETWEEN 0 AND 24) AND ("SunHours" IS NULL OR "SunHours" BETWEEN 0 AND 24) AND ("MonHours" IS NULL OR "MonHours" BETWEEN 0 AND 24) AND ("TueHours" IS NULL OR "TueHours" BETWEEN 0 AND 24) AND ("WedHours" IS NULL OR "WedHours" BETWEEN 0 AND 24) AND ("ThuHours" IS NULL OR "ThuHours" BETWEEN 0 AND 24) AND ("FriHours" IS NULL OR "FriHours" BETWEEN 0 AND 24)) NOT VALID;
ALTER TABLE "tblTracking" ADD CONSTRAINT "ck_tracking_rates" CHECK (("PayRate" IS NULL OR "PayRate" >= 0) AND ("BillRate" IS NULL OR "BillRate" >= 0) AND ("OTPayRate" IS NULL OR "OTPayRate" >= 0) AND ("BillRateOT" IS NULL OR "BillRateOT" >= 0)) NOT VALID;
ALTER TABLE "tblEmployee" ADD CONSTRAINT "ck_employee_names" CHECK (length(trim("EmFirstName")) > 0 AND length(trim("EmLastName")) > 0) NOT VALID;
ALTER TABLE "tblCustomer" ADD CONSTRAINT "ck_customer_name" CHECK (length(trim("CustBusName")) > 0) NOT VALID;
ALTER TABLE "tblProject" ADD CONSTRAINT "ck_project_dates" CHECK ("EndDate" IS NULL OR "StartDate" IS NULL OR "EndDate" >= "StartDate") NOT VALID;
ALTER TABLE "tblProject" ADD CONSTRAINT "ck_project_site" CHECK (length(trim("SiteName")) > 0) NOT VALID;

CREATE UNIQUE INDEX IF NOT EXISTS "ux_tracking_employee_project_week" ON "tblTracking" ("EmployeeID", "ProjectID", "WeekEndingDate") WHERE "Placeholder" IS NOT TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS "ux_officestaff_initials" ON "tblOfficeStaff" (lower("Initials")) WHERE "Initials" IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS "ux_employeeb_employee" ON "tblEmployeeB" ("EmployeeID") ;
