export interface LookupItem {
  id: number;
  label: string;
  extra?: Record<string, unknown> | null;
}

export interface Lookups {
  trades: LookupItem[];
  states: LookupItem[];
  cities: LookupItem[];
  employee_statuses: LookupItem[];
  qualifications: LookupItem[];
  experience: LookupItem[];
  license_types: LookupItem[];
  customer_statuses: LookupItem[];
  customer_types: LookupItem[];
  sales_statuses: LookupItem[];
  project_statuses: LookupItem[];
  wcc: LookupItem[];
  payroll_companies: LookupItem[];
  payroll_on_site: LookupItem[];
  salesmen: LookupItem[];
  contact_titles: LookupItem[];
  note_types: LookupItem[];
  divisions: LookupItem[];
  features: LookupItem[];
  /** form fields the server withholds while connected to the production database */
  restricted_fields?: string[];
  /** which data the site is showing: demo (synthetic), staging (restored copy of real data) or production (live) */
  environment?: "demo" | "staging" | "production";
  /** "search-only": a mirror of the office system, no Add/Edit/Delete; "full": the editing screens are active */
  site_mode?: "search-only" | "full";
}

export interface User {
  OfficeStaffID: number;
  OfficeStaffFirstName: string;
  OfficeStaffLastName: string;
  OfficeStaffFullName: string;
  Initials: string;
  OfficeStaffTitle: string | null;
  OfficeStaffEmail: string | null;
  Profile: boolean;
  OfficeStaffActive: boolean;
  OfficeStaffCanDelete: boolean;
  OfficeStaffEmployeeResearch: boolean;
  OfficeStaffHideHours: boolean;
  OfficeStaffTrackingReportEmailReceive: boolean;
  feature_ids: number[];
  features: string[];
  /** real data: admin (WEB_ADMINS) | user (WEB_USERS, look-up only) | none; demo: admin | features */
  web_access?: "admin" | "user" | "none" | "features";
  /** real data: "settings" (bootstrap list on the server), "store" (granted on this page), "none" */
  web_access_source?: "settings" | "store" | "none";
  /** true on the search-only mirror: no Add/Edit/Delete for anyone, administrators included */
  search_only?: boolean;
}

/** When the information was last refreshed from the office system (the search-only mirror). */
export interface SyncStatus {
  applies: boolean;
  search_only?: boolean;
  source?: string;
  last_success_at?: string | null;
  age_hours?: number | null;
  stale_after_hours?: number;
  level?: "fresh" | "aging" | "stale" | "never";
  stale?: boolean;
  next_expected_at?: string | null;
  last_run?: { status: string; started_at: string; error: string | null } | null;
  message?: string | null;
}

/** How many people may use the website, how many used it this month, and the seat limit of the sign-in service. */
export interface AccessSummary {
  authorized: number;
  administrators: number;
  users: number;
  used_this_month: number;
  seat_limit: number | null;
  seats_left: number | null;
  warning: boolean;
  message: string | null;
}

export type Filters = Record<string, string | number | boolean | null>;

export interface AISearchInfo {
  mode: "claude" | "heuristic" | "manual";
  query: string;
  interpretation: string;
  filters: Filters;
  keywords: string[];
  summary?: string;
  suggestions?: { label: string; patch: Filters }[];
}

export interface Facet {
  key: string;
  label: string;
  values: { value: string; count: number }[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  ai?: AISearchInfo | null;
  facets?: Facet[] | null;
}

export interface EmployeeSummary {
  EmployeeID: number;
  EmFirstName: string;
  EmLastName: string;
  full_name: string;
  EmCity: string | null;
  EmState: string | null;
  EmMobilePhone: string | null;
  EmEmail: string | null;
  status_name: string | null;
  trade_name: string | null;
  qualification_name: string | null;
  experience_name: string | null;
  YearsInTrade: number | null;
  BaseSalary: number | null;
  OSHA10: string | null;
  PostEmployeeAsAvailable: boolean;
  EmLicenseDateExpires: string | null;
  license_count: number;
  last_week_ending: string | null;
  score: number | null;
}

export interface EmployeeLicense {
  EmployeeLicenseID?: number;
  EmployeeLicenseStateID: number | null;
  EmployeeLicenseTradeID: number | null;
  EmployeeLicenseTypeID: number | null;
  EmployeeLicenseNumber: string | null;
  EmployeeLicenseExpDate: string | null;
  EmployeeLicenseCopyOnFile: string | null;
  EmployeeLicenseNotes: string | null;
  state_code?: string | null;
  trade_name?: string | null;
  license_type_name?: string | null;
}

export interface EmployeeNote {
  EmployeeNoteID: number;
  EmployeeNote: string;
  EmployeeNoteUserName: string | null;
  EmployeeNoteTimestamp: string;
  EmployeeNoteTypeID: number | null;
  note_type_name: string | null;
}

export interface TrackingSummary {
  TrackingID: number;
  CustomerID: number;
  EmployeeID: number;
  ProjectID: number;
  WeekEndingDate: string;
  AssignWeek: number;
  AssignYear: number;
  employee_name: string | null;
  customer_name: string | null;
  site_name: string | null;
  payroll_on_site: string | null;
  PayRate: number;
  BillRate: number;
  TotalHours: number;
  RegularHours: number;
  OvertimeHours: number;
  InvoiceAmount: number;
  EmGrossPayroll: number;
  CalcProfitMargin: number | null;
  Grade: string | null;
  DirVerified: boolean;
  Placeholder: boolean;
}

export interface Employee extends Record<string, unknown> {
  EmployeeID: number;
  EmFirstName: string;
  EmLastName: string;
  full_name: string;
  status_name: string | null;
  trade_name: string | null;
  qualification_name: string | null;
  licenses: EmployeeLicense[];
  notes: EmployeeNote[];
  recent_assignments: TrackingSummary[];
  EmEntryUserName: string | null;
  EmEntryTimestamp: string;
  /** the record as it was read; sent back as expected_version so a save over someone else's change is refused */
  version?: string | null;
}

/** One line of the change history (the website's own log; never the Access password or restricted columns). */
export interface AuditEntry {
  id: number;
  at: string;
  staff_id: number | null;
  initials: string | null;
  action: string;
  table: string;
  record_id: number | null;
  summary: string | null;
  changes: Record<string, { from: unknown; to: unknown }>;
  request_id: string | null;
}

export interface CustomerSummary {
  CustomerID: number;
  CustBusName: string;
  City: string | null;
  State: string | null;
  Phone: string | null;
  CustEmail: string | null;
  status_name: string | null;
  type_name: string | null;
  salesman_name: string | null;
  sales_status_name: string | null;
  Industry: string | null;
  ContractOnFile: boolean;
  OnHold: boolean;
  RevenuePerYear: number | null;
  project_count: number;
  active_project_count: number;
  score: number | null;
}

export interface CustomerContact {
  CustomerContactID?: number;
  CustomerContactFName: string;
  CustomerContactLName: string;
  CustomerContactTitleID: number | null;
  CustomerContactEmail: string | null;
  CustomerContactCell: string | null;
  CustomerContactOfficePhone: string | null;
  CustomerContactNotes: string | null;
  CustomerContactPriority: number;
  title_name?: string | null;
}

export interface CustomerNote {
  CustomerNoteID: number;
  CustomerNote: string;
  CustomerNoteUserName: string | null;
  CustomerNoteTimestamp: string;
}

export interface ProjectSummary {
  ProjectID: number;
  CustomerID: number;
  customer_name: string | null;
  SiteName: string;
  SiteCity: string | null;
  SiteState: string | null;
  StartDate: string | null;
  EndDate: string | null;
  status_name: string | null;
  wcc_code: string | null;
  NumberOfEmployees: number;
  JobBeingManned: boolean;
  ContractAmount: number | null;
  assigned_count: number;
  score: number | null;
}

export interface Customer extends Record<string, unknown> {
  CustomerID: number;
  CustBusName: string;
  status_name: string | null;
  type_name: string | null;
  salesman_name: string | null;
  contacts: CustomerContact[];
  notes: CustomerNote[];
  projects: ProjectSummary[];
  CustEntryUserName: string | null;
  CustEntryTimestamp: string;
  version?: string | null;
}

export interface Project extends Record<string, unknown> {
  ProjectID: number;
  CustomerID: number;
  SiteName: string;
  customer_name: string | null;
  status_name: string | null;
  wcc_code: string | null;
  wcc_desc: string | null;
  assignments: TrackingSummary[];
  ProjectEntryUserName: string | null;
  ProjectEntryTimestamp: string;
  version?: string | null;
}

export interface Tracking extends TrackingSummary {
  PayrollCoOnSiteID: number | null;
  OTPayRate: number | null;
  BillRateOT: number | null;
  SatHours: number;
  SunHours: number;
  MonHours: number;
  TueHours: number;
  WedHours: number;
  ThuHours: number;
  FriHours: number;
  WCC: string | null;
  HoursNote: string | null;
  DirectionsSentEmail: boolean;
  DirectionsSentText: boolean;
  PayrollInfoSent: boolean;
  version?: string | null;
}

export interface DashboardStats {
  employees_total: number;
  employees_active: number;
  employees_available: number;
  customers_total: number;
  customers_active: number;
  projects_total: number;
  projects_active: number;
  assignments_this_week: number;
  hours_this_week: number;
  invoice_this_week: number;
  payroll_this_week: number;
  margin_this_week: number | null;
  users_total: number;
  licenses_expiring_90d: number;
  week_ending: string;
  top_trades: { trade: string; count: number }[];
  weekly_hours: { week_ending: string; hours: number; invoice: number; payroll: number; workers: number }[];
  recent_activity: { when: string; user: string; action: string; object_id: number | null }[];
  ai_mode: "claude" | "heuristic";
}

export type Entity = "employees" | "customers" | "projects";

export interface DuplicateMatch {
  id: number;
  name: string;
  score: number;
  level: "likely" | "possible";
  reasons: string[];
  city: string | null;
  state: string | null;
  phone: string | null;
  email: string | null;
  status: string | null;
}


export interface SystemStatus {
  environment: string;
  environment_label: string;
  ai_mode: string;
  claude_model: string | null;
  database: { data_source: string; server_configured: boolean; server: string | null; expected_server_name: string | null; database: string; auth: string; driver: string; driver_installed: boolean; writes_allowed: boolean; write_approval_recorded: boolean; mode: string };
  schema_check: { source: string; ok: boolean; tables_checked: number; columns_checked: number; missing_tables: string[]; type_mismatches: string[] };
  sign_in: { store: string; accounts_with_web_password: number; demo_sign_in_offered: boolean; lockout: string; minimum_password_length: number };
  restricted_fields: string[];
  restricted_fields_withheld: boolean;
  production_writes: string;
  warnings: string[];
}

/** an approved-device record (the second boundary behind the site password) */
export interface WebDevice {
  id: number;
  status: "pending" | "approved" | "revoked";
  pairing_code: string | null;
  label: string | null;
  staff_id: number | null;
  created_at: string | null;
  created_ip: string | null;
  user_agent: string | null;
  approved_at: string | null;
  approved_by: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  last_used_at: string | null;
  last_ip: string | null;
  uses: number;
  backed_up: boolean | null;
}

export type UnlockResult =
  | { stage: "session"; access_token: string; user: User; must_change_password?: boolean }
  | { stage: "device"; ticket: string; rp_id: string };
