"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")


_EMPTY_FOR = {bool: False, int: 0, float: 0.0, str: ""}


class ORM(BaseModel):
    """Base of every response model."""
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="before")
    @classmethod
    def _empty_instead_of_null(cls, value, info):
        # The real McLabor database has NULL in columns the demo always fills (crew size on 15,746 of 15,748 jobs,
        # hours and rates on thousands of tracking rows). A record must still open: NULL is shown as 0 / empty.
        if value is None:
            field = cls.model_fields.get(info.field_name)
            if field is not None and field.annotation in _EMPTY_FOR:
                return _EMPTY_FOR[field.annotation]
        elif isinstance(value, datetime):
            # the McLabor structure stores dates in datetime columns (PostgreSQL: timestamp); a date field takes the date part
            field = cls.model_fields.get(info.field_name)
            if field is not None and field.annotation in (date, date | None):
                return value.date()
        return value


# --------------------------------------------------------------- input rules
# Validation for create/update payloads only.  Kept out of the *Base classes on
# purpose: the *Out response models inherit those, and legacy rows in the
# production database must still be readable even if they break today's rules.
import re as _re  # noqa: E402

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _required_text(v: object, label: str) -> str:
    if v is None or not str(v).strip():
        raise ValueError(f"{label} is required")
    return str(v).strip()


def _optional_email(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip()
    if not _EMAIL_RE.match(v):
        raise ValueError("is not a valid e-mail address")
    return v


def _optional_phone(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    digits = _re.sub(r"\D", "", v)
    if not 7 <= len(digits) <= 15:
        raise ValueError("must contain 7-15 digits")
    return v.strip()


def _optional_state(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    if not _re.fullmatch(r"[A-Za-z]{2}", v.strip()):
        raise ValueError("must be a 2-letter state code")
    return v.strip().upper()


def _range(v: float | int | None, lo: float, hi: float) -> float | int | None:
    if v is not None and not lo <= v <= hi:
        raise ValueError(f"must be between {lo:g} and {hi:g}")
    return v


class EmployeeInputRules(BaseModel):
    @field_validator("EmFirstName", "EmLastName", mode="before", check_fields=False)
    @classmethod
    def _names(cls, v, info):
        return _required_text(v, "First name" if info.field_name == "EmFirstName" else "Last name")

    @field_validator("EmEmail", check_fields=False)
    @classmethod
    def _email(cls, v):
        return _optional_email(v)

    @field_validator("EmMobilePhone", "EmHomePhone", check_fields=False)
    @classmethod
    def _phone(cls, v):
        return _optional_phone(v)

    @field_validator("EmState", check_fields=False)
    @classmethod
    def _state(cls, v):
        return _optional_state(v)

    @field_validator("YearsInTrade", check_fields=False)
    @classmethod
    def _years(cls, v):
        return _range(v, 0, 70)

    @field_validator("BaseSalary", check_fields=False)
    @classmethod
    def _rate(cls, v):
        return _range(v, 0, 1000)

    @field_validator("EmDOB", check_fields=False)
    @classmethod
    def _dob(cls, v):
        if v is not None:
            today = date.today()
            if v > today or (today.year - v.year) < 14 or (today.year - v.year) > 100:
                raise ValueError("date of birth is not plausible")
        return v


class CustomerInputRules(BaseModel):
    @field_validator("CustBusName", mode="before", check_fields=False)
    @classmethod
    def _name(cls, v):
        return _required_text(v, "Business name")

    @field_validator("CustEmail", check_fields=False)
    @classmethod
    def _email(cls, v):
        return _optional_email(v)

    @field_validator("Phone", "CustFaxNum", check_fields=False)
    @classmethod
    def _phone(cls, v):
        return _optional_phone(v)

    @field_validator("State", check_fields=False)
    @classmethod
    def _state(cls, v):
        return _optional_state(v)

    @field_validator("CreditLimit", "RevenuePerYear", "LaborRateAFrom", "LaborRateATo", "LaborRateBFrom", "LaborRateBTo", check_fields=False)
    @classmethod
    def _money(cls, v):
        return _range(v, 0, 1e10)


class ProjectInputRules(BaseModel):
    @field_validator("SiteName", mode="before", check_fields=False)
    @classmethod
    def _name(cls, v):
        return _required_text(v, "Site name")

    @field_validator("CustomerID", mode="before", check_fields=False)
    @classmethod
    def _customer(cls, v):
        if v is None:
            raise ValueError("Customer is required")
        return v

    @field_validator("NumberOfEmployees", "ARateQty", "BRateQty", "CRateQty", check_fields=False)
    @classmethod
    def _counts(cls, v):
        return _range(v, 0, 10000)

    @model_validator(mode="after")
    def _dates(self):
        start, end = getattr(self, "StartDate", None), getattr(self, "EndDate", None)
        if start and end and end < start:
            raise ValueError("End date cannot be before the start date")
        return self


class Facet(BaseModel):
    key: str
    label: str
    values: list[dict[str, Any]]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    ai: AISearchInfo | None = None
    facets: list[Facet] | None = None


# ---------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    username: str = Field(..., description="Initials or e-mail")
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    must_change_password: bool = False


# ---------------------------------------------------------------- lookups
class LookupItem(BaseModel):
    id: int
    label: str
    extra: dict[str, Any] | None = None


class Lookups(BaseModel):
    restricted_fields: list[str] = []  # form fields hidden while connected to real data
    environment: str = "demo"  # demo | staging | production
    site_mode: str = "full"  # "search-only": a mirror of the office system, no Add/Edit/Delete for anyone
    trades: list[LookupItem]
    states: list[LookupItem]
    cities: list[LookupItem]
    employee_statuses: list[LookupItem]
    qualifications: list[LookupItem]
    experience: list[LookupItem]
    license_types: list[LookupItem]
    customer_statuses: list[LookupItem]
    customer_types: list[LookupItem]
    sales_statuses: list[LookupItem]
    project_statuses: list[LookupItem]
    wcc: list[LookupItem]
    payroll_companies: list[LookupItem]
    payroll_on_site: list[LookupItem]
    salesmen: list[LookupItem]
    contact_titles: list[LookupItem]
    note_types: list[LookupItem]
    divisions: list[LookupItem]
    features: list[LookupItem]


# ---------------------------------------------------------------- users
class UserBase(BaseModel):
    OfficeStaffFirstName: str
    OfficeStaffLastName: str
    Initials: str = Field(..., min_length=1, max_length=5)
    OfficeStaffTitle: str | None = None
    OfficeStaffEmail: str | None = None
    Profile: bool = False
    OfficeStaffActive: bool = True
    OfficeStaffCanDelete: bool = False
    OfficeStaffEmployeeResearch: bool = False
    OfficeStaffHideHours: bool = False
    OfficeStaffTrackingReportEmailReceive: bool = False
    feature_ids: list[int] = []


class UserCreate(UserBase):
    password: str = Field(..., min_length=6)


class UserUpdate(BaseModel):
    OfficeStaffFirstName: str | None = None
    OfficeStaffLastName: str | None = None
    Initials: str | None = None
    OfficeStaffTitle: str | None = None
    OfficeStaffEmail: str | None = None
    Profile: bool | None = None
    OfficeStaffActive: bool | None = None
    OfficeStaffCanDelete: bool | None = None
    OfficeStaffEmployeeResearch: bool | None = None
    OfficeStaffHideHours: bool | None = None
    OfficeStaffTrackingReportEmailReceive: bool | None = None
    feature_ids: list[int] | None = None
    password: str | None = Field(None, min_length=6)


class UserOut(ORM):
    OfficeStaffID: int
    OfficeStaffFirstName: str
    OfficeStaffLastName: str
    OfficeStaffFullName: str
    Initials: str
    OfficeStaffTitle: str | None
    OfficeStaffEmail: str | None
    Profile: bool
    OfficeStaffActive: bool
    OfficeStaffCanDelete: bool
    OfficeStaffEmployeeResearch: bool
    OfficeStaffHideHours: bool
    OfficeStaffTrackingReportEmailReceive: bool
    feature_ids: list[int] = []
    features: list[str] = []
    # Real data: "admin" (WEB_ADMINS), "user" (WEB_USERS, look-up only) or "none". Demo: "admin" or "features".
    web_access: str = "features"
    # Real data: where the role comes from - "settings" (bootstrap list in backend.env), "store" (granted on the Users page), "none"
    web_access_source: str = "none"
    # True on the search-only mirror: no Add/Edit/Delete for anyone, administrators included
    search_only: bool = False


# ---------------------------------------------------------------- employees
class EmployeeLicenseIn(BaseModel):
    EmployeeLicenseStateID: int | None = None
    EmployeeLicenseTradeID: int | None = None
    EmployeeLicenseTypeID: int | None = None
    EmployeeLicenseNumber: str | None = None
    EmployeeLicenseExpDate: date | None = None
    EmployeeLicenseCopyOnFile: str | None = None
    EmployeeLicenseNotes: str | None = None


class EmployeeLicenseOut(EmployeeLicenseIn, ORM):
    EmployeeLicenseID: int
    state_code: str | None = None
    trade_name: str | None = None
    license_type_name: str | None = None


class EmployeeNoteIn(BaseModel):
    EmployeeNote: str = Field(..., min_length=1)
    EmployeeNoteTypeID: int | None = None
    EmployeeNoteCustomerID: int | None = None


class EmployeeNoteOut(ORM):
    EmployeeNoteID: int
    EmployeeNote: str
    EmployeeNoteUserName: str | None
    EmployeeNoteTimestamp: datetime
    EmployeeNoteTypeID: int | None
    note_type_name: str | None = None


class EmployeeBase(BaseModel):
    EmFirstName: str = Field(..., min_length=1)
    EmLastName: str = Field(..., min_length=1)
    EmMiddle: str | None = None
    EmStreet: str | None = None
    EmStateCityID: int | None = None
    EmCity: str | None = None
    EmState: str | None = None
    EmZip: str | None = None
    EmHomePhone: str | None = None
    EmMobilePhone: str | None = None
    EmEmail: str | None = None
    EmEmployeeStatusID: int | None = None
    EmQualificationID: int | None = None
    EmTradeID: int | None = None
    SubTrade1ID: int | None = None
    SubTrade2ID: int | None = None
    EmExperienceID: int | None = None
    YearsInTrade: int | None = None
    EmLicenseNum: str | None = None
    EmLicenseDateExpires: date | None = None
    EmLicensedIn: str | None = None
    OSHA10: str | None = None
    BaseSalary: float | None = None
    EmDOB: date | None = None
    EmReferredBy: str | None = None
    ReferrerEmployeeID: int | None = None
    EmContractWith_PayrollCoID: int | None = None
    USCitizen: bool = True
    I9Complete: bool = False
    JobApplComplete: bool = False
    EmApplComplete: bool = False
    Recruiter: bool = False
    PostEmployeeAsAvailable: bool = False
    EmployeeNoCommunication: bool = False
    WillTravel: str | None = None
    EmAdminNotes: str | None = None
    EmSalesNotes: str | None = None


class EmployeeCreate(EmployeeInputRules, EmployeeBase):
    licenses: list[EmployeeLicenseIn] = []
    allow_duplicate: bool = Field(False, description="Create even if likely duplicates exist (user confirmed).")


class EmployeeUpdate(EmployeeInputRules, BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str | None = Field(None, description="The record's version when the form was opened; the save is refused if it changed since.")
    EmFirstName: str | None = None
    EmLastName: str | None = None
    EmMiddle: str | None = None
    EmStreet: str | None = None
    EmStateCityID: int | None = None
    EmCity: str | None = None
    EmState: str | None = None
    EmZip: str | None = None
    EmHomePhone: str | None = None
    EmMobilePhone: str | None = None
    EmEmail: str | None = None
    EmEmployeeStatusID: int | None = None
    EmQualificationID: int | None = None
    EmTradeID: int | None = None
    SubTrade1ID: int | None = None
    SubTrade2ID: int | None = None
    EmExperienceID: int | None = None
    YearsInTrade: int | None = None
    EmLicenseNum: str | None = None
    EmLicenseDateExpires: date | None = None
    EmLicensedIn: str | None = None
    OSHA10: str | None = None
    BaseSalary: float | None = None
    EmDOB: date | None = None
    EmReferredBy: str | None = None
    ReferrerEmployeeID: int | None = None
    EmContractWith_PayrollCoID: int | None = None
    USCitizen: bool | None = None
    I9Complete: bool | None = None
    JobApplComplete: bool | None = None
    EmApplComplete: bool | None = None
    Recruiter: bool | None = None
    PostEmployeeAsAvailable: bool | None = None
    EmployeeNoCommunication: bool | None = None
    WillTravel: str | None = None
    EmAdminNotes: str | None = None
    EmSalesNotes: str | None = None
    licenses: list[EmployeeLicenseIn] | None = None


class EmployeeSummary(ORM):
    EmployeeID: int
    EmFirstName: str
    EmLastName: str
    full_name: str
    EmCity: str | None
    EmState: str | None
    EmMobilePhone: str | None
    EmEmail: str | None
    status_name: str | None = None
    trade_name: str | None = None
    qualification_name: str | None = None
    experience_name: str | None = None
    YearsInTrade: int | None
    BaseSalary: float | None
    OSHA10: str | None
    PostEmployeeAsAvailable: bool
    EmLicenseDateExpires: date | None
    license_count: int = 0
    last_week_ending: date | None = None
    score: float | None = None
    reasons: list[str] = []


class EmployeeOut(EmployeeBase, ORM):
    EmployeeID: int
    # None while the restricted columns are withheld (production)
    USCitizen: bool | None = None
    I9Complete: bool | None = None
    full_name: str
    status_name: str | None = None
    trade_name: str | None = None
    sub_trade1_name: str | None = None
    sub_trade2_name: str | None = None
    qualification_name: str | None = None
    experience_name: str | None = None
    payroll_co_name: str | None = None
    EmEntryUserName: str | None
    EmEntryTimestamp: datetime | None = None
    version: str | None = None  # send back as expected_version when saving
    licenses: list[EmployeeLicenseOut] = []
    notes: list[EmployeeNoteOut] = []
    recent_assignments: list[TrackingSummary] = []


# ---------------------------------------------------------------- customers
class CustomerContactIn(BaseModel):
    CustomerContactFName: str
    CustomerContactLName: str
    CustomerContactTitleID: int | None = None
    CustomerContactEmail: str | None = None
    CustomerContactCell: str | None = None
    CustomerContactOfficePhone: str | None = None
    CustomerContactNotes: str | None = None
    CustomerContactPriority: int = 1


class CustomerContactOut(CustomerContactIn, ORM):
    CustomerContactID: int
    title_name: str | None = None


class CustomerNoteIn(BaseModel):
    CustomerNote: str = Field(..., min_length=1)


class CustomerNoteOut(ORM):
    CustomerNoteID: int
    CustomerNote: str
    CustomerNoteUserName: str | None
    CustomerNoteTimestamp: datetime
    CustomerNoteActive: bool


class CustomerBase(BaseModel):
    CustBusName: str = Field(..., min_length=1)
    Street: str | None = None
    StateCityID: int | None = None
    City: str | None = None
    State: str | None = None
    Zip: str | None = None
    Phone: str | None = None
    CustEmail: str | None = None
    CustFaxNum: str | None = None
    CustWebSiteHLink: str | None = None
    CustStatusID: int | None = None
    CustomerTypeID: int | None = None
    SalesmanID: int | None = None
    SalesStatusID: int | None = None
    CustContractWith_PayrollCoID: int | None = None
    ContractOnFile: bool = False
    ContractDate: date | None = None
    CreditLimit: float | None = None
    RevenuePerYear: float | None = None
    LaborRateAFrom: float | None = None
    LaborRateATo: float | None = None
    LaborRateBFrom: float | None = None
    LaborRateBTo: float | None = None
    BillRateOTMultiplier: float | None = 1.5
    Industry: str | None = None
    EmployeeSize: str | None = None
    CustomerDescription: str | None = None
    CustomerNote: str | None = None
    InvoiceNote: str | None = None
    CollectionsNote: str | None = None
    OnHold: bool = False
    FutureSales: bool = False
    FutureCall: date | None = None
    CustomerLicenseNumber: str | None = None


class CustomerCreate(CustomerInputRules, CustomerBase):
    contacts: list[CustomerContactIn] = []
    allow_duplicate: bool = Field(False, description="Create even if likely duplicates exist (user confirmed).")


class CustomerUpdate(CustomerInputRules, BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str | None = None
    CustBusName: str | None = None
    Street: str | None = None
    StateCityID: int | None = None
    City: str | None = None
    State: str | None = None
    Zip: str | None = None
    Phone: str | None = None
    CustEmail: str | None = None
    CustFaxNum: str | None = None
    CustWebSiteHLink: str | None = None
    CustStatusID: int | None = None
    CustomerTypeID: int | None = None
    SalesmanID: int | None = None
    SalesStatusID: int | None = None
    CustContractWith_PayrollCoID: int | None = None
    ContractOnFile: bool | None = None
    ContractDate: date | None = None
    CreditLimit: float | None = None
    RevenuePerYear: float | None = None
    LaborRateAFrom: float | None = None
    LaborRateATo: float | None = None
    LaborRateBFrom: float | None = None
    LaborRateBTo: float | None = None
    BillRateOTMultiplier: float | None = None
    Industry: str | None = None
    EmployeeSize: str | None = None
    CustomerDescription: str | None = None
    CustomerNote: str | None = None
    InvoiceNote: str | None = None
    CollectionsNote: str | None = None
    OnHold: bool | None = None
    FutureSales: bool | None = None
    FutureCall: date | None = None
    CustomerLicenseNumber: str | None = None
    contacts: list[CustomerContactIn] | None = None


class CustomerSummary(ORM):
    CustomerID: int
    CustBusName: str
    City: str | None
    State: str | None
    Phone: str | None
    CustEmail: str | None
    status_name: str | None = None
    type_name: str | None = None
    salesman_name: str | None = None
    sales_status_name: str | None = None
    Industry: str | None
    ContractOnFile: bool
    OnHold: bool
    RevenuePerYear: float | None
    project_count: int = 0
    active_project_count: int = 0
    score: float | None = None
    reasons: list[str] = []


class ProjectSummary(ORM):
    ProjectID: int
    CustomerID: int
    customer_name: str | None = None
    SiteName: str
    SiteCity: str | None
    SiteState: str | None
    StartDate: date | None
    EndDate: date | None
    status_name: str | None = None
    wcc_code: str | None = None
    NumberOfEmployees: int
    JobBeingManned: bool
    ContractAmount: float | None
    assigned_count: int = 0
    score: float | None = None
    reasons: list[str] = []


class CustomerOut(CustomerBase, ORM):
    CustomerID: int
    status_name: str | None = None
    type_name: str | None = None
    salesman_name: str | None = None
    sales_status_name: str | None = None
    payroll_co_name: str | None = None
    CustEntryUserName: str | None
    CustEntryTimestamp: datetime
    version: str | None = None
    contacts: list[CustomerContactOut] = []
    notes: list[CustomerNoteOut] = []
    projects: list[ProjectSummary] = []


# ---------------------------------------------------------------- projects
class ProjectBase(BaseModel):
    CustomerID: int
    SiteName: str = Field(..., min_length=1)
    SiteStreet: str | None = None
    SiteStateCityID: int | None = None
    SiteCity: str | None = None
    SiteState: str | None = None
    SiteZip: str | None = None
    StartDate: date | None = None
    EndDate: date | None = None
    ProjStatusID: int | None = None
    ProjectWCCID: int | None = None
    ProjNote: str | None = None
    ProjOfficeNote: str | None = None
    JobNote: str | None = None
    ProjStartTime: str | None = None
    OCIPJob: bool = False
    RateJob: bool = False
    ShiftDifferential: bool = False
    JobBeingManned: bool = False
    GCOnSite: bool = False
    ARateQty: int = 0
    BRateQty: int = 0
    CRateQty: int = 0
    NumberOfEmployees: int = 0
    ContractAmount: float | None = None
    ContractTotalPayments: float | None = None
    ContractBalanceOwed: float | None = None
    CustomerContact: str | None = None
    CustomerPhone: str | None = None
    CustomerEmail: str | None = None
    ParentProjectID: int | None = None


class ProjectCreate(ProjectInputRules, ProjectBase):
    pass


class ProjectUpdate(ProjectInputRules, BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str | None = None
    CustomerID: int | None = None
    SiteName: str | None = None
    SiteStreet: str | None = None
    SiteStateCityID: int | None = None
    SiteCity: str | None = None
    SiteState: str | None = None
    SiteZip: str | None = None
    StartDate: date | None = None
    EndDate: date | None = None
    ProjStatusID: int | None = None
    ProjectWCCID: int | None = None
    ProjNote: str | None = None
    ProjOfficeNote: str | None = None
    JobNote: str | None = None
    ProjStartTime: str | None = None
    OCIPJob: bool | None = None
    RateJob: bool | None = None
    ShiftDifferential: bool | None = None
    JobBeingManned: bool | None = None
    GCOnSite: bool | None = None
    ARateQty: int | None = None
    BRateQty: int | None = None
    CRateQty: int | None = None
    NumberOfEmployees: int | None = None
    ContractAmount: float | None = None
    ContractTotalPayments: float | None = None
    ContractBalanceOwed: float | None = None
    CustomerContact: str | None = None
    CustomerPhone: str | None = None
    CustomerEmail: str | None = None
    ParentProjectID: int | None = None


class ProjectOut(ProjectBase, ORM):
    ProjectID: int
    customer_name: str | None = None
    status_name: str | None = None
    wcc_code: str | None = None
    wcc_desc: str | None = None
    ProjectEntryUserName: str | None
    ProjectEntryTimestamp: datetime | None = None
    version: str | None = None
    assignments: list[TrackingSummary] = []


# ---------------------------------------------------------------- tracking
class TrackingBase(BaseModel):
    CustomerID: int
    EmployeeID: int
    ProjectID: int
    WeekEndingDate: date
    PayrollCoOnSiteID: int | None = None
    PayRate: float = 0
    OTPayRate: float | None = None
    BillRate: float = 0
    BillRateOT: float | None = None
    SatHours: float = 0
    SunHours: float = 0
    MonHours: float = 0
    TueHours: float = 0
    WedHours: float = 0
    ThuHours: float = 0
    FriHours: float = 0
    WCC: str | None = None
    Grade: str | None = None
    HoursNote: str | None = None
    DirectionsSentEmail: bool = False
    DirectionsSentText: bool = False
    DirVerified: bool = False
    PayrollInfoSent: bool = False
    Placeholder: bool = False


class TrackingCreate(TrackingBase):
    pass


class TrackingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str | None = None
    CustomerID: int | None = None
    EmployeeID: int | None = None
    ProjectID: int | None = None
    WeekEndingDate: date | None = None
    PayrollCoOnSiteID: int | None = None
    PayRate: float | None = None
    OTPayRate: float | None = None
    BillRate: float | None = None
    BillRateOT: float | None = None
    SatHours: float | None = None
    SunHours: float | None = None
    MonHours: float | None = None
    TueHours: float | None = None
    WedHours: float | None = None
    ThuHours: float | None = None
    FriHours: float | None = None
    WCC: str | None = None
    Grade: str | None = None
    HoursNote: str | None = None
    DirectionsSentEmail: bool | None = None
    DirectionsSentText: bool | None = None
    DirVerified: bool | None = None
    PayrollInfoSent: bool | None = None
    Placeholder: bool | None = None


class TrackingSummary(ORM):
    TrackingID: int
    CustomerID: int
    EmployeeID: int
    ProjectID: int
    WeekEndingDate: date
    AssignWeek: int
    AssignYear: int
    employee_name: str | None = None
    customer_name: str | None = None
    site_name: str | None = None
    payroll_on_site: str | None = None
    PayRate: float
    BillRate: float
    TotalHours: float
    RegularHours: float
    OvertimeHours: float
    InvoiceAmount: float
    EmGrossPayroll: float
    CalcProfitMargin: float | None
    Grade: str | None
    DirVerified: bool
    Placeholder: bool


class TrackingOut(TrackingBase, ORM):
    TrackingID: int
    AssignWeek: int
    AssignYear: int
    employee_name: str | None = None
    customer_name: str | None = None
    site_name: str | None = None
    payroll_on_site: str | None = None
    TotalHours: float
    RegularHours: float
    OvertimeHours: float
    InvoiceAmount: float
    EmGrossPayroll: float
    CalcProfitMargin: float | None
    AssignmentUserName: str | None
    AssignmentTimestamp: datetime | None = None
    version: str | None = None


# ---------------------------------------------------------------- AI search
class AISearchInfo(BaseModel):
    mode: Literal["claude", "heuristic", "manual"]
    query: str
    interpretation: str
    filters: dict[str, Any]
    keywords: list[str] = []
    summary: str = ""
    suggestions: list[dict[str, Any]] = []


class AISearchRequest(BaseModel):
    entity: Literal["employees", "customers", "projects"]
    query: str | None = Field(None, max_length=500)
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=100)
    sort: str | None = None
    # Interactive refinement: either override the filters outright...
    filters: dict[str, Any] | None = None
    keywords: list[str] | None = None
    # ...or interpret `query` as a follow-up that builds on the previous filters.
    refine: bool = False
    base_filters: dict[str, Any] | None = None
    base_keywords: list[str] | None = None


# ---------------------------------------------------------------- dashboard
class DashboardStats(BaseModel):
    employees_total: int
    employees_active: int
    employees_available: int
    customers_total: int
    customers_active: int
    projects_total: int
    projects_active: int
    assignments_this_week: int
    hours_this_week: float
    invoice_this_week: float
    payroll_this_week: float
    margin_this_week: float | None
    users_total: int
    licenses_expiring_90d: int
    week_ending: date
    top_trades: list[dict[str, Any]]
    weekly_hours: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]
    ai_mode: Literal["claude", "heuristic"]


Page.model_rebuild()
TokenResponse.model_rebuild()
EmployeeOut.model_rebuild()
CustomerOut.model_rebuild()
ProjectOut.model_rebuild()
