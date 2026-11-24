import { buildQuery } from "./format";
import type {
  AccessSummary, AISearchInfo, AuditEntry, Customer, DuplicateMatch, CustomerNote, CustomerSummary, DashboardStats, Employee, EmployeeNote, EmployeeSummary, Entity,
  Facet, Filters, Lookups, Page, Project, SyncStatus, SystemStatus, ProjectSummary, Tracking, TrackingSummary, User,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "mclabor.token";

/** How people get in: "open" = demo, no sign-in; "login" = sign-in page; "gateway" = the company gateway signs people in. */
export type AccessMode = "open" | "login" | "gateway";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

/** Candidates returned with a 409 when a create looks like an existing record. */
export function duplicateMatches(e: unknown): DuplicateMatch[] | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const d = e.detail as { detail?: { matches?: DuplicateMatch[] } } | undefined;
  return Array.isArray(d?.detail?.matches) ? d!.detail!.matches! : null;
}

/** 409 "someone else changed this record since you opened it": the message to show, or null. */
export function staleConflict(e: unknown): string | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const d = e.detail as { detail?: { code?: string; message?: string } } | undefined;
  return d?.detail?.code === "stale" ? d.detail.message ?? "This record was changed by someone else. Reload it and try again." : null;
}

export function describeError(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { detail?: unknown } | undefined;
    if (d && typeof d.detail === "string") return d.detail;
    if (d && d.detail && typeof d.detail === "object" && "message" in (d.detail as object)) return String((d.detail as { message: unknown }).message);
    if (d && Array.isArray(d.detail)) {
      return d.detail.map((x: { loc?: unknown[]; msg?: string }) => `${(x.loc ?? []).slice(1).join(".")}: ${x.msg}`).join("; ");
    }
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers as Record<string, string> | undefined) };
  if (init.body) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is the backend running?`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      setToken(null);
      window.dispatchEvent(new Event("mclabor:unauthorized"));
    }
    throw new ApiError(res.status, (data && data.detail && typeof data.detail === "string") ? data.detail : `Request failed (${res.status})`, data);
  }
  return data as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  // auth
  login: (username: string, password: string) => request<{ access_token: string; user: User; must_change_password?: boolean }>("/api/auth/login", { method: "POST", body: json({ username, password }) }),
  me: () => request<User>("/api/auth/me"),
  changePassword: (current_password: string, new_password: string) => request<void>("/api/auth/change-password", { method: "POST", body: json({ current_password, new_password }) }),
  setUserPassword: (id: number, password: string, must_change = true) => request<void>(`/api/users/${id}/password`, { method: "POST", body: json({ password, must_change }) }),
  health: () => request<{ status: string; ai_mode: string; demo?: boolean; database?: string; environment?: string; access_mode?: AccessMode; site_mode?: "search-only" | "full" }>("/api/health"),
  /** last successful refresh from the office system (search-only mirror); applies=false in the demo */
  syncStatus: () => request<SyncStatus>("/api/sync/status"),
  lookups: () => request<Lookups>("/api/lookups"),
  systemStatus: () => request<SystemStatus>("/api/system/status"),
  dashboard: () => request<DashboardStats>("/api/dashboard"),

  // employees
  employees: (params: Record<string, string | number | boolean | null | undefined>) => request<Page<EmployeeSummary>>(`/api/employees${buildQuery(params)}`),
  employee: (id: number) => request<Employee>(`/api/employees/${id}`),
  createEmployee: (body: unknown) => request<Employee>("/api/employees", { method: "POST", body: json(body) }),
  updateEmployee: (id: number, body: unknown) => request<Employee>(`/api/employees/${id}`, { method: "PUT", body: json(body) }),
  deleteEmployee: (id: number) => request<void>(`/api/employees/${id}`, { method: "DELETE" }),
  checkEmployeeDuplicates: (body: Record<string, unknown>) => request<{ matches: DuplicateMatch[] }>("/api/employees/check-duplicates", { method: "POST", body: json(body) }),
  addEmployeeNote: (id: number, body: { EmployeeNote: string; EmployeeNoteTypeID?: number | null }) => request<EmployeeNote>(`/api/employees/${id}/notes`, { method: "POST", body: json(body) }),

  // customers
  customers: (params: Record<string, string | number | boolean | null | undefined>) => request<Page<CustomerSummary>>(`/api/customers${buildQuery(params)}`),
  customer: (id: number) => request<Customer>(`/api/customers/${id}`),
  createCustomer: (body: unknown) => request<Customer>("/api/customers", { method: "POST", body: json(body) }),
  updateCustomer: (id: number, body: unknown) => request<Customer>(`/api/customers/${id}`, { method: "PUT", body: json(body) }),
  deleteCustomer: (id: number) => request<void>(`/api/customers/${id}`, { method: "DELETE" }),
  checkCustomerDuplicates: (body: Record<string, unknown>) => request<{ matches: DuplicateMatch[] }>("/api/customers/check-duplicates", { method: "POST", body: json(body) }),
  addCustomerNote: (id: number, body: { CustomerNote: string }) => request<CustomerNote>(`/api/customers/${id}/notes`, { method: "POST", body: json(body) }),

  // projects
  projects: (params: Record<string, string | number | boolean | null | undefined>) => request<Page<ProjectSummary>>(`/api/projects${buildQuery(params)}`),
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (body: unknown) => request<Project>("/api/projects", { method: "POST", body: json(body) }),
  updateProject: (id: number, body: unknown) => request<Project>(`/api/projects/${id}`, { method: "PUT", body: json(body) }),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  // tracking
  trackingWeeks: () => request<{ current: string; weeks: string[] }>("/api/tracking/weeks"),
  tracking: (params: Record<string, string | number | boolean | null | undefined>) => request<Page<TrackingSummary>>(`/api/tracking${buildQuery(params)}`),
  trackingOne: (id: number) => request<Tracking>(`/api/tracking/${id}`),
  createTracking: (body: unknown) => request<Tracking>("/api/tracking", { method: "POST", body: json(body) }),
  updateTracking: (id: number, body: unknown) => request<Tracking>(`/api/tracking/${id}`, { method: "PUT", body: json(body) }),
  deleteTracking: (id: number) => request<void>(`/api/tracking/${id}`, { method: "DELETE" }),

  // users
  users: (params: Record<string, string | number | boolean | null | undefined>) => request<Page<User>>(`/api/users${buildQuery(params)}`),
  createUser: (body: unknown) => request<User>("/api/users", { method: "POST", body: json(body) }),
  updateUser: (id: number, body: unknown) => request<User>(`/api/users/${id}`, { method: "PUT", body: json(body) }),
  deactivateUser: (id: number) => request<void>(`/api/users/${id}`, { method: "DELETE" }),
  /** real data: grant or remove website access (admin / user / none); effective on the person's next request */
  setWebAccess: (id: number, role: "admin" | "user" | "none") => request<User>(`/api/users/${id}/web-access`, { method: "PUT", body: json({ role }) }),
  accessSummary: () => request<AccessSummary>("/api/users/access-summary"),

  // change history (who changed what, when)
  history: (entity: "employees" | "customers" | "projects" | "tracking", id: number) => request<{ items: AuditEntry[] }>(`/api/audit/${entity}/${id}`),
  recentChanges: (params: Record<string, string | number | boolean | null | undefined>) => request<{ items: AuditEntry[] }>(`/api/audit${buildQuery(params)}`),

  // AI search
  searchStatus: () => request<{ mode: "claude" | "heuristic"; examples: Record<Entity, string[]> }>("/api/search/status"),
  aiSearch: <T>(entity: Entity, query: string, page = 1, page_size = 50) =>
    request<Page<T> & { ai: AISearchInfo }>("/api/search", { method: "POST", body: json({ entity, query, page, page_size }) }),
  /** Interactive search: override filters directly, or refine with a follow-up query. */
  aiSearchAdvanced: <T>(body: { entity: Entity; query?: string; page?: number; page_size?: number; sort?: string; filters?: Filters; keywords?: string[]; refine?: boolean; base_filters?: Filters; base_keywords?: string[] }) =>
    request<Page<T> & { ai: AISearchInfo; facets: Facet[] }>("/api/search", { method: "POST", body: json({ page: 1, page_size: 50, ...body }) }),
};
