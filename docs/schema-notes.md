# SQL Server schema notes (from the two CSV exports)

Source files: `McLabor_Database_structure.csv` (3,507 columns across 298 tables/views) and
`McLabor_table_relationship.csv` (260 foreign-key relationships). Columns: schema, table, column, type
and relationship name, child table/column, parent table/column respectively.

## Core entities used by the web app

| Table | Cols | Role | Key relationships |
|---|---|---|---|
| `tblEmployee` | 254 | Worker master record (name, address, phones, trade, qualification, license, rates, onboarding flags, notes) | `EmTradeID`→`tblPullDownTrade`, `EmQualificationID`→`tblPullDownQualifications`, `EmExperienceID`→`tblPullDownExperience`, `EmEmployeeStatusID`→`tblPullDownEmployeeStatus`, `EmStateCityID`→`tblPullDownStateCities`, `ReferrerEmployeeID`→`tblEmployee` (self), `EmContractWith_PayrollCoID`→`tblPullDownContractWith_PayrollCo` |
| `tblEmployeeB` | 125 | Overflow/extension of tblEmployee (DOT, PPE, extra phones/emails, license status, flags) | 1:1 on `EmployeeID` |
| `tblEmployeeLicenses` | 9 | Multiple licenses per employee | `EmployeeLicenseStateID`→States, `EmployeeLicenseTradeID`→Trade, `EmployeeLicenseTypeID`→LicenseTypes |
| `tblEmployeeNotes` | 13 | Timestamped notes with type / review type | →`tblEmployee`, →NoteTypes, →ReviewTypes |
| `tblCustomer` | 249 | Customer (contractor) master record incl. per-payroll-company insurance/contract links, AR colors, verification stamps | `CustomerTypeID`, `CustStatusID`, `SalesmanID`/`ContractSalesmanID`/`HunterID`→`tblPullDownSalesman`, `StateCityID`, `CustContractWith_PayrollCoID` |
| `tblCustomerContacts` | 18 | Contacts per customer with priority & title | →`tblCustomer`, →ContactTitles, →CellCarriers |
| `tblCustomerNotes` | 6 | Free-text notes | →`tblCustomer` |
| `tblProject` | 144 | Job / site record incl. NOI/NOC/lien paperwork, GC verification, rates mix | `CustomerID`→`tblCustomer`, `ProjStatusID`→ProjStatus, `SiteStateCityID`, `ProjectWCCID`→`tblPullDownWCC`, `SiteForemanID`→`tblCustomerForeman`, `ParentProjectID` (self) |
| `tblTracking` | 137 | One row per employee × project × week: hours Sat–Fri, pay/bill rates, benefits/referral per-hour costs, calculated payroll, invoice & margin | →Customer, →Employee, →Project, →PayrollCoOnSite, day status flags→`tblPullDownStatusFlag` |
| `tblOfficeStaff` | 21 | Application users (initials, password, Profile=admin, CanDelete, e-mail flags) | – |
| `tblFeature` / `tblOfficeStaffPermission` | 19 / 3 | Feature catalogue and per-user grants (many-to-many) | →`tblOfficeStaff`, →`tblFeature` |
| `tblOfficeStaffActivity` / `tblOfficeStaffLogin` | 7 / 8 | Audit of screens opened and logins | →`tblOfficeStaff` |

## Patterns observed

* **Audit stamps everywhere** – most editable columns have a sibling `<Column>UserName` + `<Column>Timestamp`
  pair (e.g. `EmMobilePhoneUserName`, `EmMobilePhoneTimestamp`). The demo records the editing user's initials on
  the row-level `*EntryUserName` and in `tblOfficeStaffActivity`; per-column stamps can be added the same way.
* **Denormalised copies** – `tblTracking` snapshots customer/site/employee text (`CustomerBusName`, `SiteName`,
  `EmLastName`…) at assignment time; `tblEmployee`/`tblCustomer` store both `StateCityID` and literal `City`/`State`.
  The demo keeps `City`/`State` in sync from the `StateCityID` lookup on save.
* **Lookup tables** are all prefixed `tblPullDown*` with `<Name>ID`, `<Name>`, `<Name>Sort` (and often `Active`).
  There are ~110 of them; the demo seeds the 20 the UI needs.
* **Payroll companies** – `tblPullDownContractWith_PayrollCo` (who the customer contracts with) vs
  `tblPullDownPayrollCoOnSite` (whose payroll the worker is on for that week).
* **Workers' comp** – `tblPullDownWCC` class codes attach to projects and customers; `tblWccRates` holds per-state rates.
* **Weeks** – `AssignWeek`/`AssignYear` + `WeekEndingDate`; hours columns run Sat→Fri so the week ends on Friday.
* **Web tables already present** – `WebCustomerSavedView`, `WebEmployeeSavedView`, `WebEmployeeSearchPreset` suggest a
  previous web front-end stored per-user grid layouts as JSON; the new app can reuse them for saved searches.
* **Money fields** use the SQL `money` type; several derived margin/cost fields (`CalcProfitMargin`,
  `TotalPayrollWccCode`, …) are stored rather than computed. `Tracking.recompute()` in the demo mirrors the basic ones.

## Not modelled in the demo (candidates for later phases)

Accident reports, certified payroll, NOI/NOC lien workflow, customer payments/deposits/AR aging, health-insurance
quotes, referral-agency payments, unemployment requests, commissions/clusters, e-mail templates, KB/help topics,
mileage logs, QuickBooks open-invoice import.
