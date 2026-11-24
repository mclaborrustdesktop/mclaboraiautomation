# Replacing Microsoft Access: workflow audit and gaps (2026-11-24)

Method: the two Access files on this PC's Desktop (`2026 11-06 MLS 5-44-0.accdb`, 601 MB, and `Database.mdb`) were
scanned as bytes for object names only (never opened in Access, no record read, no password printed:
`tools/access-audit/scan_access_objects.py` + `group_access_objects.py`). After removing deleted-object remnants and
numbered copies: **2,196 form names, 384 report names, 3,016 query names**. Grouped by functional area and compared
with the website and with the 298 tables of the schema export.

Many forms are variants of one screen (the Access application has one form per search layout, per sub-form, per
"holding" copy), so the number of *workflows* is far smaller than the number of forms. The areas below are the
workflows the office actually runs.

## 1. Covered by the website today (synthetic data; on real data once the environment is approved)

| Access area (forms / reports) | Website | Notes |
|---|---|---|
| Employee data entry, search, notes, licenses (`frmEmployeeDataEntry*`, `frmAddNewEmployee*`, `frmEmployeeSearch*`, 424 forms) | Employees: list, filters, keyword and AI search, record page, Add/Edit form with validation and duplicate check, licenses, notes, **change history**, "changed by someone else" protection | contact history / references / questions / tool lists / bio sub-forms: not built (section 3) |
| Customer data entry, search, contacts, notes, sales status (`frmCustomerDataEntry*`, `frmCustomerSearch*`, 357 forms) | Customers: list, filters, search, record page, Add/Edit with duplicate check, contacts, notes, jobs list, change history | AKA names, permits, insurance-certificate requirements, bill-rate table, research notes: not built |
| Job / project data entry and search (`frmProjectDataEntry*`, `frmAddNewProject`, `frmPostAJob`) | Jobs: list, filters, search, record page, Add/Edit, weekly assignments, change history | NOI/NOC lien paperwork, GC verification, accident reports, owners, BMFs: not built |
| Weekly tracking: new assignment, edit hours and rates, end assignment, copy forward, placeholders (`frmNewAssignment`, `frmTrackingEdit*`, `frmCopyTrackingForward`, 135 forms) | Weekly tracking board by week, assign one or many workers, hours per day with regular/overtime/invoice/payroll/margin recomputed, rules (0-24 h, rates, duplicates, do-not-contact), delete rights | copy week forward, placeholders, directions e-mail/text, lock weeks: not built |
| Users, permissions, logins (`frmOfficeStaff*`, `frmOfficeStaffPermission`, `frmLogin`) | Users page with roles, website access (maximum 20), activity, web passwords, Cloudflare sign-in | the 1,100 Access-form permissions are replaced by two website roles |
| Lookup lists used by the forms (`frmPullDown*` for trades, statuses, cities, WCC, payroll companies...) | read by the website; blank and inactive entries refused on save | maintenance screens for the lists themselves: not built (section 3) |
| Dashboard figures (week totals, trades, licences expiring) | Dashboard | |

## 2. Not yet supported: ranked by how often the office needs it

| # | Access workflow | Tables in the schema | Size |
|---|---|---|---|
| G1 | **Copy a week's assignments forward** to next week (`frmCopyTrackingForward`), end an assignment, placeholders (`tblPlaceholderAssignmentHistory`) | `tblTracking`, `tblPlaceholderAssignmentHistory` | 2-3 days |
| G2 | **Lookup list maintenance** (add a trade, a city, a WCC code, a status) with Active flags | all `tblPullDown*` | 2 days (one generic screen) |
| G3 | **Reports: manpower schedule, verify hours, hours not in, directions** (`rptManpowerSchedule`, `rptVerifyWorkHours`, `rptAllHoursNotIn`, `rptJobDirections`) as printable pages / Excel | `tblTracking`, `tblProject` | 3-4 days |
| G4 | **Payroll export and reports** (`frmPayrollReportSearch`, `rptTotalPayrollReport`, `rptPayrollReportXcelHR` / `IPG`, timesheets, crosschecks, mismatches, exclusions) | `tblTracking`, `tblPayrollAdjustments`, `tblPayrollCrosschecks`, `tblPayrollExclusions`, `tblEmployeeAdjustments/Advances/SickHours/VacationHours/Four01K*` | 2-3 weeks: the payroll-company file formats (XcelHR, IPG) must be obtained from the office |
| G5 | **Invoicing and accounts receivable** (`frmQBOpenInvoices*`, `frmAccountsReceivableSearch`, `frmCustomerPayments`, `frmMakeDeposits`, statements, aging) | `tblQBOpenInvoices` (22 cols), `tblCustomerPayments`, `tblCustomerInvoicePayments`, `tblDeposits`, `tblWeeklyProfitAndLossReport` | 2-3 weeks |
| G6 | **QuickBooks link** (QODBC "QuickBooks Data" on an office PC: open invoices read into `tblQBOpenInvoices`) | `tblQBOpenInvoices` | import of the QuickBooks export file: 3 days; QuickBooks Online API: 1-2 weeks + accountant's approval |
| G7 | **Lien / notice paperwork** (`rptNoticeOfIdentification*`, `rptNoticeOfContract*`, `rptNoticeToOwnerPrelien*`, `rptStopPaymentNotice*`, per state MA/NH/NY/IL/ME; `frmProjectNOIFlagNotes`) | `tblProject` (NOI/NOC columns), `tblProjectOwners`, `tblProjectGeneralContractors` | 1-2 weeks (document templates) |
| G8 | **Sales commissions and clusters** (`frmCommissionsSearch`, `frmClusterCommissions*`, `rptCommissionsReport`, `rptSalesBySalesman*`) | `tblCommissions`, `tblClusterCommissions*`, `tblClusters`, `tblClusterCities` | 1-2 weeks |
| G9 | **Workers' comp rates and insurance certificates** (`frmWccRates`, `frmCustomerDataEntryInsuranceCertReqs`, `rptWccRatesReport`) | `tblWccRates`, `tblWccRatesAudit`, `tblCustomerInsuranceCertReqs`, `tblCustomerWCCs` | 1 week |
| G10 | **Accident reports** (`frmProjectAccidentReport*`, 56-column table) | `tblProjectAccidentReports*` | 1 week |
| G11 | **Health insurance, benefits, unemployment requests** (`frmEmployeeHealthInsurance*`, `frmUnemploymentRequests`) | `tblEmployeeHealthInsurance*`, `tblUnemploymentRequests` | 1-2 weeks |
| G12 | **Employee sub-records**: contact history, references, schooling, questions, tools, bios, previous employers, car notes, DOT/PPE (`tblEmployeeB`) | `tblEmployeeContacts/ContactHistory/References/Schooling/Questions/Tools/Bios`, `tblEmployeeB` | 1-2 weeks (generic sub-record editor) |
| G13 | **E-mail and letter templates, mail merge, newsletters, postcards** (`frmEmailTemplates`, `rptEmployeeLetter`, `rptCustomerPostcard`, `tblFormLetterTemplates`) | `tblEmailTemplates`, `tblFormLetter*`, `tblNewsletterContacts` | 1-2 weeks; needs an e-mail service decision |
| G14 | **Referral agencies** (payments, invoices, weeks) | `tblReferralAgency*`, `tblPullDownReferralAgencies` | 1 week |
| G15 | Alerts, reminders, messages, help/KB, mileage log, imports, research, DataPay application matching | `tblAlerts`, `tblReminders`, `tblKB*`, `tblMileageLog`, `tbl*Import*`, `tblEmployeeResearch*` | as needed |
| G16 | Saved searches and multi-filters (`tblMultiFilter*`, `WebEmployeeSearchPreset`, `WebCustomerSavedView`) | present in the schema | 2-3 days |

Total to replace Access **completely**: on the order of 3-4 months of development after the core (section 1) is in
daily use, with G1-G3 first (dispatch), then G4-G6 (money), then the rest. The schema generator already carries
every table these areas need into PostgreSQL, so none of them blocks the migration of the data.

## 3. Payroll, reporting and QuickBooks specifically

* **Payroll**: the website computes gross payroll, invoice and margin per week the way `tblTracking` stores them.
  It does not yet produce the payroll companies' files (XcelHR, IPG), adjustments/advances/sick/vacation/401k, or
  the crosscheck and mismatch reports. The formats come from the office (G4).
* **Reporting**: 384 Access reports fall into about 25 families; the ones used weekly are G3 (dispatch) and G4/G5
  (money). A report page in the website renders a printable HTML/Excel view from the same queries; document-style
  reports (G7 notices, letters) need templates.
* **QuickBooks**: the only integration is the QODBC read of open invoices into `tblQBOpenInvoices`. The website can
  import the QuickBooks export file into that table (G6, small) and show the AR views from it (G5).

## 4. Cross-checks done

* Every form name was matched against the website's pages and against the table list; the mapping above is by
  functional area, not by form, because the Access forms are layout variants.
* The 33 tables the website reads/writes today are all in the generated PostgreSQL schema together with the other
  255, so the migration carries the data of the unbuilt areas along for later screens.
