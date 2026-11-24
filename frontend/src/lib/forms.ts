import type { FormSection } from "@/components/EntityForm";

const YES_NO = [
  { value: "Yes", label: "Yes" },
  { value: "No", label: "No" },
  { value: "Within 50 miles", label: "Within 50 miles" },
  { value: "Statewide", label: "Statewide" },
];

export const EMPLOYEE_SECTIONS: FormSection[] = [
  {
    title: "Identity",
    fields: [
      { name: "EmFirstName", label: "First name", required: true },
      { name: "EmMiddle", label: "Middle" },
      { name: "EmLastName", label: "Last name", required: true },
      { name: "EmDOB", label: "Date of birth", type: "date" },
      { name: "EmEmployeeStatusID", label: "Status", type: "select", lookup: "employee_statuses" },
      { name: "EmContractWith_PayrollCoID", label: "Payroll company", type: "select", lookup: "payroll_companies" },
    ],
  },
  {
    title: "Contact & Address",
    fields: [
      { name: "EmMobilePhone", label: "Mobile phone", type: "tel", placeholder: "(508) 555-0100" },
      { name: "EmHomePhone", label: "Home phone", type: "tel" },
      { name: "EmEmail", label: "E-mail", type: "email" },
      { name: "EmStreet", label: "Street", span: 2 },
      { name: "EmStateCityID", label: "City / State", type: "select", lookup: "cities", help: "City and state are filled from this list" },
      { name: "EmZip", label: "ZIP" },
      { name: "WillTravel", label: "Will travel", type: "select", options: YES_NO },
    ],
  },
  {
    title: "Trade & Experience",
    fields: [
      { name: "EmTradeID", label: "Primary trade", type: "select", lookup: "trades" },
      { name: "SubTrade1ID", label: "Secondary trade", type: "select", lookup: "trades" },
      { name: "SubTrade2ID", label: "Third trade", type: "select", lookup: "trades" },
      { name: "EmQualificationID", label: "Qualification", type: "select", lookup: "qualifications" },
      { name: "EmExperienceID", label: "Experience level", type: "select", lookup: "experience" },
      { name: "YearsInTrade", label: "Years in trade", type: "number" },
      { name: "BaseSalary", label: "Base pay rate ($/hr)", type: "money" },
      { name: "OSHA10", label: "OSHA card", type: "select", options: [{ value: "OSHA 10", label: "OSHA 10" }, { value: "OSHA 30", label: "OSHA 30" }] },
      { name: "EmReferredBy", label: "Referred by" },
    ],
  },
  {
    title: "Primary License",
    fields: [
      { name: "EmLicenseNum", label: "License number" },
      { name: "EmLicenseDateExpires", label: "License expires", type: "date" },
      { name: "EmLicensedIn", label: "Licensed in (state)" },
    ],
  },
  {
    title: "Onboarding & Flags",
    fields: [
      { name: "USCitizen", label: "US citizen", type: "checkbox" },
      { name: "I9Complete", label: "I-9 complete", type: "checkbox" },
      { name: "JobApplComplete", label: "Job application complete", type: "checkbox" },
      { name: "EmApplComplete", label: "Employment paperwork complete", type: "checkbox" },
      { name: "PostEmployeeAsAvailable", label: "Post as available", type: "checkbox" },
      { name: "Recruiter", label: "Acts as recruiter", type: "checkbox" },
      { name: "EmployeeNoCommunication", label: "No communication (do not contact)", type: "checkbox" },
    ],
  },
  {
    title: "Notes",
    fields: [
      { name: "EmAdminNotes", label: "Admin notes", type: "textarea", span: 3 },
      { name: "EmSalesNotes", label: "Sales notes", type: "textarea", span: 3 },
    ],
  },
];

export const CUSTOMER_SECTIONS: FormSection[] = [
  {
    title: "Company",
    fields: [
      { name: "CustBusName", label: "Business name", required: true, span: 2 },
      { name: "CustomerTypeID", label: "Customer type", type: "select", lookup: "customer_types" },
      { name: "CustStatusID", label: "Status", type: "select", lookup: "customer_statuses" },
      { name: "SalesStatusID", label: "Sales status", type: "select", lookup: "sales_statuses" },
      { name: "SalesmanID", label: "Sales rep", type: "select", lookup: "salesmen" },
      { name: "Industry", label: "Industry" },
      { name: "EmployeeSize", label: "Company size", type: "select", options: ["1-10", "11-50", "51-200", "200+"].map((v) => ({ value: v, label: v })) },
      { name: "CustContractWith_PayrollCoID", label: "Contract with (payroll co.)", type: "select", lookup: "payroll_companies" },
    ],
  },
  {
    title: "Contact & Address",
    fields: [
      { name: "Phone", label: "Phone", type: "tel" },
      { name: "CustFaxNum", label: "Fax", type: "tel" },
      { name: "CustEmail", label: "E-mail", type: "email" },
      { name: "Street", label: "Street", span: 2 },
      { name: "StateCityID", label: "City / State", type: "select", lookup: "cities" },
      { name: "Zip", label: "ZIP" },
      { name: "CustWebSiteHLink", label: "Website", span: 2 },
      { name: "CustomerLicenseNumber", label: "Contractor license #" },
    ],
  },
  {
    title: "Contract & Billing",
    fields: [
      { name: "ContractOnFile", label: "Contract on file", type: "checkbox" },
      { name: "ContractDate", label: "Contract date", type: "date" },
      { name: "CreditLimit", label: "Credit limit", type: "money" },
      { name: "RevenuePerYear", label: "Revenue per year", type: "money" },
      { name: "LaborRateAFrom", label: "A-rate from ($/hr)", type: "money" },
      { name: "LaborRateATo", label: "A-rate to ($/hr)", type: "money" },
      { name: "LaborRateBFrom", label: "B-rate from ($/hr)", type: "money" },
      { name: "LaborRateBTo", label: "B-rate to ($/hr)", type: "money" },
      { name: "BillRateOTMultiplier", label: "OT bill multiplier", type: "money" },
      { name: "OnHold", label: "On hold", type: "checkbox" },
      { name: "FutureSales", label: "Future sales opportunity", type: "checkbox" },
      { name: "FutureCall", label: "Future call date", type: "date" },
    ],
  },
  {
    title: "Notes",
    fields: [
      { name: "CustomerDescription", label: "Description", type: "textarea", span: 3 },
      { name: "CustomerNote", label: "Customer note", type: "textarea", span: 3 },
      { name: "InvoiceNote", label: "Invoice note", type: "textarea", span: 3 },
      { name: "CollectionsNote", label: "Collections note", type: "textarea", span: 3 },
    ],
  },
];

export const PROJECT_SECTIONS: FormSection[] = [
  {
    title: "Job",
    fields: [
      { name: "SiteName", label: "Site / job name", required: true, span: 2 },
      { name: "ProjStatusID", label: "Status", type: "select", lookup: "project_statuses" },
      { name: "StartDate", label: "Start date", type: "date" },
      { name: "EndDate", label: "Projected end date", type: "date" },
      { name: "ProjStartTime", label: "Start time", placeholder: "7:00 AM" },
      { name: "ProjectWCCID", label: "Workers' comp class (WCC)", type: "select", lookup: "wcc", span: 2 },
      { name: "NumberOfEmployees", label: "Workers needed", type: "number" },
    ],
  },
  {
    title: "Site Address",
    fields: [
      { name: "SiteStreet", label: "Street", span: 2 },
      { name: "SiteStateCityID", label: "City / State", type: "select", lookup: "cities" },
      { name: "SiteZip", label: "ZIP" },
    ],
  },
  {
    title: "Site Contact",
    fields: [
      { name: "CustomerContact", label: "On-site contact" },
      { name: "CustomerPhone", label: "Contact phone", type: "tel" },
      { name: "CustomerEmail", label: "Contact e-mail", type: "email" },
    ],
  },
  {
    title: "Rates & Flags",
    fields: [
      { name: "ARateQty", label: "A-rate workers", type: "number" },
      { name: "BRateQty", label: "B-rate workers", type: "number" },
      { name: "CRateQty", label: "C-rate workers", type: "number" },
      { name: "ContractAmount", label: "Contract amount", type: "money" },
      { name: "ContractTotalPayments", label: "Payments received", type: "money" },
      { name: "ContractBalanceOwed", label: "Balance owed", type: "money" },
      { name: "JobBeingManned", label: "Job is being manned", type: "checkbox" },
      { name: "OCIPJob", label: "OCIP job", type: "checkbox" },
      { name: "RateJob", label: "Rate job", type: "checkbox" },
      { name: "ShiftDifferential", label: "Shift differential", type: "checkbox" },
      { name: "GCOnSite", label: "GC on site", type: "checkbox" },
    ],
  },
  {
    title: "Notes",
    fields: [
      { name: "ProjNote", label: "Site instructions (sent to workers)", type: "textarea", span: 3 },
      { name: "JobNote", label: "Job note", type: "textarea", span: 3 },
      { name: "ProjOfficeNote", label: "Office-only note", type: "textarea", span: 3 },
    ],
  },
];

export function pickInitial(record: Record<string, unknown> | null, sections: FormSection[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const s of sections) {
    for (const f of s.fields) {
      const v = record?.[f.name];
      out[f.name] = v === null || v === undefined ? (f.type === "checkbox" ? false : "") : v;
    }
  }
  return out;
}
