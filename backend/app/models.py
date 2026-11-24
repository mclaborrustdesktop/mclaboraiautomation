"""ORM models.

These mirror the subset of the MC Labor SQL Server schema (see
docs/schema-notes.md) that the web application needs.  Table and column
names are kept identical to production so the app can later be pointed at
the real database.  Only the columns the UI uses are declared; SQLAlchemy
ignores the extra production columns.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, literal_column, select, table
from sqlalchemy import column as sa_column
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from .config import settings
from .database import Base

# The production schema stores a few values the demo keeps as plain columns somewhere else
# (see docs/schema - checked by `python -m app.production schema`).  In the production shape (SQL Server, or the
# PostgreSQL database built from the same structure) those attributes become SQL expressions over the real tables;
# writes to them are mapped back by derived.py.
_PRODUCTION = settings.production_shape
_tblEmployeeB = table("tblEmployeeB", sa_column("EmployeeBID"), sa_column("EmployeeID"), sa_column("WillTravel"))
_tblYearsInTrade = table("tblPullDownYearsInTrade", sa_column("PullDownYearsInTradeID"), sa_column("PullDownYearsInTrade"))
# the leading number of a years-in-trade label ("5 years", "25+ years"), per database engine
_YEARS_FROM_LABEL = (
    "NULLIF(substring(yit.\"PullDownYearsInTrade\" from '^[0-9]+'), '')::int" if settings.is_postgres
    else "TRY_CAST(LEFT(yit.PullDownYearsInTrade, PATINDEX('%[^0-9]%', yit.PullDownYearsInTrade + 'x') - 1) AS int)" if settings.is_sql_server
    else "CAST(yit.PullDownYearsInTrade AS int)"  # SQLite (synthetic production-shape file): CAST reads the leading digits
)


def now() -> datetime:
    return datetime.utcnow()


# --------------------------------------------------------------------------
# Lookup ("PullDown") tables
# --------------------------------------------------------------------------
class PullDownDivision(Base):
    __tablename__ = "tblPullDownDivisions"
    PullDownDivisionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownDivision: Mapped[str] = mapped_column(String(100))
    PullDownDivisionSort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownDivisionActive: Mapped[bool] = mapped_column(Boolean, default=True)


class PullDownTrade(Base):
    __tablename__ = "tblPullDownTrade"
    PullDownTradeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownTrade: Mapped[str] = mapped_column(String(100))
    PullDownTradeSwitch: Mapped[str | None] = mapped_column(String(20))
    PullDownTradeSort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownTradeDivisionID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownDivisions.PullDownDivisionID"))


class PullDownState(Base):
    __tablename__ = "tblPullDownStates"
    PullDownStateID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownState: Mapped[str] = mapped_column(String(2))
    PullDownStateName: Mapped[str] = mapped_column(String(50))
    PullDownStateSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownStateCity(Base):
    __tablename__ = "tblPullDownStateCities"
    PullDownStateCityID: Mapped[int] = mapped_column(Integer, primary_key=True)
    StateID: Mapped[int] = mapped_column(ForeignKey("tblPullDownStates.PullDownStateID"))
    City: Mapped[str] = mapped_column(String(100))
    PullDownStateCitySort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownStateCityActive: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[PullDownState] = relationship()


class PullDownEmployeeStatus(Base):
    __tablename__ = "tblPullDownEmployeeStatus"
    PullDownEmployeeStatusID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownEmployeeStatus: Mapped[str] = mapped_column(String(50))
    PullDownEmployeeStatusSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownQualification(Base):
    __tablename__ = "tblPullDownQualifications"
    PullDownQualificationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownQualification: Mapped[str] = mapped_column(String(100))
    PullDownQualificationSort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownQualificationDivisionID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownDivisions.PullDownDivisionID"))


class PullDownExperience(Base):
    __tablename__ = "tblPullDownExperience"
    PullDownExperienceID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownExperience: Mapped[str] = mapped_column(String(50))
    PullDownExperienceSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownLicenseType(Base):
    __tablename__ = "tblPullDownLicenseTypes"
    PullDownLicenseTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownLicenseType: Mapped[str] = mapped_column(String(100))
    PullDownLicenseTypeSort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownLicenseTypeActive: Mapped[bool] = mapped_column(Boolean, default=True)


class PullDownCustStatus(Base):
    __tablename__ = "tblPullDownCustStatus"
    PulldownCustStatusID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PulldownCustStatus: Mapped[str] = mapped_column(String(50))
    PulldownCustStatusSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownCustomerType(Base):
    __tablename__ = "tblPullDownCustomerTypes"
    PullDownCustomerTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownCustomerType: Mapped[str] = mapped_column(String(100))
    PullDownCustomerTypeSort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownCustomerTypeDivisionID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownDivisions.PullDownDivisionID"))


class PullDownSalesStatus(Base):
    __tablename__ = "tblPullDownSalesStatus"
    PullDownSalesStatusID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownSalesStatus: Mapped[str] = mapped_column(String(50))
    PullDownSalesStatusSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownProjStatus(Base):
    __tablename__ = "tblPullDownProjStatus"
    PullDownProjStatusID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownProjStatus: Mapped[str] = mapped_column(String(50))
    PullDownProjStatusSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownWCC(Base):
    __tablename__ = "tblPullDownWCC"
    PullDownWCCID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownWCC: Mapped[str] = mapped_column(String(20))
    PullDownWCCDesc: Mapped[str] = mapped_column(String(200))
    PullDownWCCSort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownWCCActive: Mapped[bool] = mapped_column(Boolean, default=True)
    PullDownWCCDivisionID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownDivisions.PullDownDivisionID"))


class PullDownContractWithPayrollCo(Base):
    __tablename__ = "tblPullDownContractWith_PayrollCo"
    PullDownContractWith_PayrollCoID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownContractWith_PayrollCoName: Mapped[str] = mapped_column(String(100))
    PullDownContractWith_PayrollCoInitials: Mapped[str] = mapped_column(String(10))
    PullDownContractWith_PayrollCoSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownPayrollCoOnSite(Base):
    __tablename__ = "tblPullDownPayrollCoOnSite"
    PullDownPayrollCoOnSiteID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownPayrollCoOnSiteName: Mapped[str] = mapped_column(String(100))
    PullDownPayrollCoOnSiteInitials: Mapped[str] = mapped_column(String(10))
    PullDownPayrollCoOnSiteSort: Mapped[int] = mapped_column(Integer, default=0)
    PullDownPayrollCoOnSiteActive: Mapped[bool] = mapped_column(Boolean, default=True)


class PullDownStatusFlag(Base):
    __tablename__ = "tblPullDownStatusFlag"
    PullDownStatusFlagID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownStatusFlag: Mapped[str] = mapped_column(String(10))
    PullDownStatusFlagDesc: Mapped[str] = mapped_column(String(100))
    PullDownStatusFlagSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownSalesman(Base):
    __tablename__ = "tblPullDownSalesman"
    PullDownSalesmanID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownSalesmanFName: Mapped[str] = mapped_column(String(50))
    PullDownSalesmanLName: Mapped[str] = mapped_column(String(50))
    PullDownSalesmanTitle: Mapped[str | None] = mapped_column(String(50))
    PullDownSalesmanEmail: Mapped[str | None] = mapped_column(String(120))
    PullDownSalesmanCell: Mapped[str | None] = mapped_column(String(30))
    PullDownSalesmanSort: Mapped[int] = mapped_column(Integer, default=0)
    OfficeStaffID: Mapped[int | None] = mapped_column(ForeignKey("tblOfficeStaff.OfficeStaffID"))
    PullDownSalesmanActive: Mapped[bool] = mapped_column(Boolean, default=True)


class PullDownCustomerContactTitle(Base):
    __tablename__ = "tblPullDownCustomerContactTitles"
    PullDownCustomerContactTitleID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownCustomerContactTitle: Mapped[str] = mapped_column(String(60))
    PullDownCustomerContactTitleSort: Mapped[int] = mapped_column(Integer, default=0)


class PullDownEmployeeNoteType(Base):
    __tablename__ = "tblPullDownEmployeeNoteTypes"
    PullDownEmployeeNoteTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PullDownEmployeeNoteType: Mapped[str] = mapped_column(String(60))
    PullDownEmployeeNoteTypeSort: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------
# Office staff (application users) + feature permissions
# --------------------------------------------------------------------------
class OfficeStaff(Base):
    __tablename__ = "tblOfficeStaff"
    OfficeStaffID: Mapped[int] = mapped_column(Integer, primary_key=True)
    OfficeStaffFirstName: Mapped[str] = mapped_column(String(50))
    OfficeStaffLastName: Mapped[str] = mapped_column(String(50))
    OfficeStaffFullName: Mapped[str] = mapped_column(String(101))
    if not _PRODUCTION:
        # Demo database only (the column is NOT NULL there). Sign-in never reads it: web passwords are in webauth.py.
        # In production the Access password column is not mapped, so the app cannot request it.
        OfficeStaffPassword: Mapped[str] = mapped_column(String(300), default="web-auth")
    OfficeStaffCanDelete: Mapped[bool] = mapped_column(Boolean, default=False)
    Profile: Mapped[bool] = mapped_column(Boolean, default=False)  # admin profile
    OfficeStaffActive: Mapped[bool] = mapped_column(Boolean, default=True)
    Initials: Mapped[str] = mapped_column(String(5))
    OfficeStaffTitle: Mapped[str | None] = mapped_column(String(80))
    OfficeStaffEmail: Mapped[str | None] = mapped_column(String(120))
    OfficeStaffEmployeeResearch: Mapped[bool] = mapped_column(Boolean, default=False)
    OfficeStaffHideHours: Mapped[bool] = mapped_column(Boolean, default=False)
    OfficeStaffTrackingReportEmailReceive: Mapped[bool] = mapped_column(Boolean, default=False)

    permissions: Mapped[list[OfficeStaffPermission]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )


class Feature(Base):
    __tablename__ = "tblFeature"
    FeatureID: Mapped[int] = mapped_column(Integer, primary_key=True)
    ObjectName: Mapped[str] = mapped_column(String(100))
    ControlName: Mapped[str | None] = mapped_column(String(100))
    FeatureTitle: Mapped[str] = mapped_column(String(100))
    FeatureDescription: Mapped[str | None] = mapped_column(String(400))
    FeatureActive: Mapped[bool] = mapped_column(Boolean, default=True)
    FeatureSort: Mapped[int] = mapped_column(Integer, default=0)


class OfficeStaffPermission(Base):
    __tablename__ = "tblOfficeStaffPermission"
    OfficeStaffPermissionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    OfficeStaffID: Mapped[int] = mapped_column(ForeignKey("tblOfficeStaff.OfficeStaffID", ondelete="CASCADE"))
    FeatureID: Mapped[int] = mapped_column(ForeignKey("tblFeature.FeatureID"))
    staff: Mapped[OfficeStaff] = relationship(back_populates="permissions")
    feature: Mapped[Feature] = relationship()


class OfficeStaffActivity(Base):
    __tablename__ = "tblOfficeStaffActivity"
    OfficeStaffActivityID: Mapped[int] = mapped_column(Integer, primary_key=True)
    OfficeStaffID: Mapped[int] = mapped_column(ForeignKey("tblOfficeStaff.OfficeStaffID"))
    OfficeStaffActivityObjectName: Mapped[str] = mapped_column(String(100))
    OfficeStaffActivityTimestampStart: Mapped[datetime] = mapped_column(DateTime, default=now)
    OfficeStaffActivityObjectID: Mapped[int | None] = mapped_column(Integer)


# --------------------------------------------------------------------------
# Employees
# --------------------------------------------------------------------------
class Employee(Base):
    __tablename__ = "tblEmployee"
    EmployeeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    EmFirstName: Mapped[str] = mapped_column(String(50))
    EmLastName: Mapped[str] = mapped_column(String(50))
    EmMiddle: Mapped[str | None] = mapped_column(String(50))
    EmStreet: Mapped[str | None] = mapped_column(String(120))
    EmStateCityID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownStateCities.PullDownStateCityID"))
    EmCity: Mapped[str | None] = mapped_column(String(100))
    EmState: Mapped[str | None] = mapped_column(String(2))
    EmZip: Mapped[str | None] = mapped_column(String(12))
    EmHomePhone: Mapped[str | None] = mapped_column(String(30))
    EmMobilePhone: Mapped[str | None] = mapped_column(String(30))
    EmEmail: Mapped[str | None] = mapped_column(String(120))
    EmEmployeeStatusID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownEmployeeStatus.PullDownEmployeeStatusID"))
    EmQualificationID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownQualifications.PullDownQualificationID"))
    EmTradeID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownTrade.PullDownTradeID"))
    SubTrade1ID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownTrade.PullDownTradeID"))
    SubTrade2ID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownTrade.PullDownTradeID"))
    EmExperienceID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownExperience.PullDownExperienceID"))
    if _PRODUCTION:
        # tblEmployee.YearsInTradeID -> tblPullDownYearsInTrade; the number is the label's leading digits.
        YearsInTradeID: Mapped[int | None] = mapped_column(Integer)
        _yit = _tblYearsInTrade.alias("yit")
        YearsInTrade: Mapped[int | None] = column_property(
            select(literal_column(_YEARS_FROM_LABEL))
            .select_from(_yit).where(_yit.c.PullDownYearsInTradeID == YearsInTradeID).scalar_subquery()
        )
    else:
        YearsInTrade: Mapped[int | None] = mapped_column(Integer)
    EmLicenseNum: Mapped[str | None] = mapped_column(String(50))
    EmLicenseDateExpires: Mapped[date | None] = mapped_column(Date)
    EmLicensedIn: Mapped[str | None] = mapped_column(String(100))
    OSHA10: Mapped[str | None] = mapped_column(String(20))
    BaseSalary: Mapped[float | None] = mapped_column(Numeric(10, 2))
    if _PRODUCTION:
        EmDOB = None  # restricted: not mapped, never requested from SQL Server
    else:
        EmDOB: Mapped[date | None] = mapped_column(Date)
    EmHowReferredID: Mapped[int | None] = mapped_column(Integer)
    EmReferredBy: Mapped[str | None] = mapped_column(String(100))
    ReferrerEmployeeID: Mapped[int | None] = mapped_column(ForeignKey("tblEmployee.EmployeeID"))
    EmContractWith_PayrollCoID: Mapped[int | None] = mapped_column(
        ForeignKey("tblPullDownContractWith_PayrollCo.PullDownContractWith_PayrollCoID")
    )
    if _PRODUCTION:
        USCitizen = None  # restricted: not mapped, never requested from SQL Server
        I9Complete = None
    else:
        USCitizen: Mapped[bool] = mapped_column(Boolean, default=True)
        I9Complete: Mapped[bool] = mapped_column(Boolean, default=False)
    JobApplComplete: Mapped[bool] = mapped_column(Boolean, default=False)
    EmApplComplete: Mapped[bool] = mapped_column(Boolean, default=False)
    Recruiter: Mapped[bool] = mapped_column(Boolean, default=False)
    PostEmployeeAsAvailable: Mapped[bool] = mapped_column(Boolean, default=False)
    EmployeeNoCommunication: Mapped[bool] = mapped_column(Boolean, default=False)
    if _PRODUCTION:
        # lives in the 1:1 extension table tblEmployeeB
        WillTravel: Mapped[str | None] = column_property(
            select(_tblEmployeeB.c.WillTravel).where(_tblEmployeeB.c.EmployeeID == EmployeeID).limit(1).scalar_subquery()
        )
    else:
        WillTravel: Mapped[str | None] = mapped_column(String(50))
    EmAdminNotes: Mapped[str | None] = mapped_column(Text)
    EmSalesNotes: Mapped[str | None] = mapped_column(Text)
    EmEntryUserName: Mapped[str | None] = mapped_column(String(50))
    EmEntryTimestamp: Mapped[datetime] = mapped_column(DateTime, default=now)
    EmployeeDuplicate: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[PullDownEmployeeStatus | None] = relationship()
    trade: Mapped[PullDownTrade | None] = relationship(foreign_keys=[EmTradeID])
    sub_trade1: Mapped[PullDownTrade | None] = relationship(foreign_keys=[SubTrade1ID])
    sub_trade2: Mapped[PullDownTrade | None] = relationship(foreign_keys=[SubTrade2ID])
    qualification: Mapped[PullDownQualification | None] = relationship()
    experience: Mapped[PullDownExperience | None] = relationship()
    payroll_co: Mapped[PullDownContractWithPayrollCo | None] = relationship()
    licenses: Mapped[list[EmployeeLicense]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    notes: Mapped[list[EmployeeNote]] = relationship(
        back_populates="employee", cascade="all, delete-orphan", order_by="desc(EmployeeNote.EmployeeNoteTimestamp)"
    )

    @property
    def full_name(self) -> str:
        return f"{self.EmFirstName} {self.EmLastName}".strip()


class EmployeeLicense(Base):
    __tablename__ = "tblEmployeeLicenses"
    EmployeeLicenseID: Mapped[int] = mapped_column(Integer, primary_key=True)
    EmployeeID: Mapped[int] = mapped_column(ForeignKey("tblEmployee.EmployeeID", ondelete="CASCADE"))
    EmployeeLicenseStateID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownStates.PullDownStateID"))
    EmployeeLicenseTradeID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownTrade.PullDownTradeID"))
    EmployeeLicenseTypeID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownLicenseTypes.PullDownLicenseTypeID"))
    EmployeeLicenseNumber: Mapped[str | None] = mapped_column(String(50))
    EmployeeLicenseExpDate: Mapped[date | None] = mapped_column(Date)
    EmployeeLicenseCopyOnFile: Mapped[str | None] = mapped_column(String(20))
    EmployeeLicenseNotes: Mapped[str | None] = mapped_column(Text)
    employee: Mapped[Employee] = relationship(back_populates="licenses")
    state: Mapped[PullDownState | None] = relationship()
    trade: Mapped[PullDownTrade | None] = relationship()
    license_type: Mapped[PullDownLicenseType | None] = relationship()


class EmployeeNote(Base):
    __tablename__ = "tblEmployeeNotes"
    EmployeeNoteID: Mapped[int] = mapped_column(Integer, primary_key=True)
    EmployeeID: Mapped[int] = mapped_column(ForeignKey("tblEmployee.EmployeeID", ondelete="CASCADE"))
    EmployeeNote: Mapped[str] = mapped_column(Text)
    EmployeeNoteUserName: Mapped[str | None] = mapped_column(String(50))
    EmployeeNoteTimestamp: Mapped[datetime] = mapped_column(DateTime, default=now)
    EmployeeNoteTypeID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownEmployeeNoteTypes.PullDownEmployeeNoteTypeID"))
    EmployeeNoteCustomerID: Mapped[int | None] = mapped_column(ForeignKey("tblCustomer.CustomerID"))
    employee: Mapped[Employee] = relationship(back_populates="notes")
    note_type: Mapped[PullDownEmployeeNoteType | None] = relationship()


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "tblCustomer"
    CustomerID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CustBusName: Mapped[str] = mapped_column(String(150))
    Street: Mapped[str | None] = mapped_column(String(120))
    StateCityID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownStateCities.PullDownStateCityID"))
    City: Mapped[str | None] = mapped_column(String(100))
    State: Mapped[str | None] = mapped_column(String(2))
    Zip: Mapped[str | None] = mapped_column(String(12))
    Phone: Mapped[str | None] = mapped_column(String(30))
    CustEmail: Mapped[str | None] = mapped_column(String(120))
    CustFaxNum: Mapped[str | None] = mapped_column(String(30))
    CustWebSiteHLink: Mapped[str | None] = mapped_column(String(200))
    CustStatusID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownCustStatus.PulldownCustStatusID"))
    CustomerTypeID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownCustomerTypes.PullDownCustomerTypeID"))
    SalesmanID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownSalesman.PullDownSalesmanID"))
    SalesStatusID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownSalesStatus.PullDownSalesStatusID"))
    CustContractWith_PayrollCoID: Mapped[int | None] = mapped_column(
        ForeignKey("tblPullDownContractWith_PayrollCo.PullDownContractWith_PayrollCoID")
    )
    ContractOnFile: Mapped[bool] = mapped_column(Boolean, default=False)
    ContractDate: Mapped[date | None] = mapped_column(Date)
    CreditLimit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    RevenuePerYear: Mapped[float | None] = mapped_column(Numeric(14, 2))
    LaborRateAFrom: Mapped[float | None] = mapped_column(Numeric(10, 2))
    LaborRateATo: Mapped[float | None] = mapped_column(Numeric(10, 2))
    LaborRateBFrom: Mapped[float | None] = mapped_column(Numeric(10, 2))
    LaborRateBTo: Mapped[float | None] = mapped_column(Numeric(10, 2))
    BillRateOTMultiplier: Mapped[float | None] = mapped_column(Float, default=1.5)
    Industry: Mapped[str | None] = mapped_column(String(100))
    EmployeeSize: Mapped[str | None] = mapped_column(String(50))
    CustomerDescription: Mapped[str | None] = mapped_column(Text)
    CustomerNote: Mapped[str | None] = mapped_column(Text)
    InvoiceNote: Mapped[str | None] = mapped_column(Text)
    CollectionsNote: Mapped[str | None] = mapped_column(Text)
    OnHold: Mapped[bool] = mapped_column(Boolean, default=False)
    FutureSales: Mapped[bool] = mapped_column(Boolean, default=False)
    FutureCall: Mapped[date | None] = mapped_column(Date)
    CustomerLicenseNumber: Mapped[str | None] = mapped_column(String(50))
    CustEntryUserName: Mapped[str | None] = mapped_column(String(50))
    CustEntryTimestamp: Mapped[datetime] = mapped_column(DateTime, default=now)

    status: Mapped[PullDownCustStatus | None] = relationship()
    customer_type: Mapped[PullDownCustomerType | None] = relationship()
    salesman: Mapped[PullDownSalesman | None] = relationship()
    sales_status: Mapped[PullDownSalesStatus | None] = relationship()
    payroll_co: Mapped[PullDownContractWithPayrollCo | None] = relationship()
    contacts: Mapped[list[CustomerContact]] = relationship(back_populates="customer", cascade="all, delete-orphan")
    notes: Mapped[list[CustomerNote]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", order_by="desc(CustomerNote.CustomerNoteTimestamp)"
    )
    projects: Mapped[list[Project]] = relationship(back_populates="customer")


class CustomerContact(Base):
    __tablename__ = "tblCustomerContacts"
    CustomerContactID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CustomerID: Mapped[int] = mapped_column(ForeignKey("tblCustomer.CustomerID", ondelete="CASCADE"))
    CustomerContactPriority: Mapped[int] = mapped_column(Integer, default=1)
    CustomerContactFName: Mapped[str] = mapped_column(String(50))
    CustomerContactLName: Mapped[str] = mapped_column(String(50))
    CustomerContactTitleID: Mapped[int | None] = mapped_column(
        ForeignKey("tblPullDownCustomerContactTitles.PullDownCustomerContactTitleID")
    )
    CustomerContactEmail: Mapped[str | None] = mapped_column(String(120))
    CustomerContactCell: Mapped[str | None] = mapped_column(String(30))
    CustomerContactOfficePhone: Mapped[str | None] = mapped_column(String(30))
    CustomerContactNotes: Mapped[str | None] = mapped_column(Text)
    CustomerContactUserName: Mapped[str | None] = mapped_column(String(50))
    CustomerContactTimestamp: Mapped[datetime] = mapped_column(DateTime, default=now)
    customer: Mapped[Customer] = relationship(back_populates="contacts")
    title: Mapped[PullDownCustomerContactTitle | None] = relationship()


class CustomerNote(Base):
    __tablename__ = "tblCustomerNotes"
    CustomerNoteID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CustomerID: Mapped[int] = mapped_column(ForeignKey("tblCustomer.CustomerID", ondelete="CASCADE"))
    CustomerNote: Mapped[str] = mapped_column(Text)
    CustomerNoteUserName: Mapped[str | None] = mapped_column(String(50))
    CustomerNoteTimestamp: Mapped[datetime] = mapped_column(DateTime, default=now)
    CustomerNoteActive: Mapped[bool] = mapped_column(Boolean, default=True)
    customer: Mapped[Customer] = relationship(back_populates="notes")


# --------------------------------------------------------------------------
# Projects (jobs)
# --------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "tblProject"
    ProjectID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CustomerID: Mapped[int] = mapped_column(ForeignKey("tblCustomer.CustomerID"))
    SiteName: Mapped[str] = mapped_column(String(150))
    SiteStreet: Mapped[str | None] = mapped_column(String(120))
    SiteStateCityID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownStateCities.PullDownStateCityID"))
    if _PRODUCTION:
        # production derives the site city/state from SiteStateCityID
        SiteCity: Mapped[str | None] = column_property(
            select(PullDownStateCity.City).where(PullDownStateCity.PullDownStateCityID == SiteStateCityID).scalar_subquery()
        )
        SiteState: Mapped[str | None] = column_property(
            select(PullDownState.PullDownState)
            .join(PullDownStateCity, PullDownStateCity.StateID == PullDownState.PullDownStateID)
            .where(PullDownStateCity.PullDownStateCityID == SiteStateCityID).scalar_subquery()
        )
    else:
        SiteCity: Mapped[str | None] = mapped_column(String(100))
        SiteState: Mapped[str | None] = mapped_column(String(2))
    SiteZip: Mapped[str | None] = mapped_column(String(12))
    StartDate: Mapped[date | None] = mapped_column(Date)
    EndDate: Mapped[date | None] = mapped_column(Date)
    ProjStatusID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownProjStatus.PullDownProjStatusID"))
    ProjectWCCID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownWCC.PullDownWCCID"))
    ProjNote: Mapped[str | None] = mapped_column(Text)
    ProjOfficeNote: Mapped[str | None] = mapped_column(Text)
    JobNote: Mapped[str | None] = mapped_column(Text)
    ProjStartTime: Mapped[str | None] = mapped_column(String(20))
    OCIPJob: Mapped[bool] = mapped_column(Boolean, default=False)
    RateJob: Mapped[bool] = mapped_column(Boolean, default=False)
    ShiftDifferential: Mapped[bool] = mapped_column(Boolean, default=False)
    JobBeingManned: Mapped[bool] = mapped_column(Boolean, default=False)
    GCOnSite: Mapped[bool] = mapped_column(Boolean, default=False)
    ARateQty: Mapped[int] = mapped_column(Integer, default=0)
    BRateQty: Mapped[int] = mapped_column(Integer, default=0)
    CRateQty: Mapped[int] = mapped_column(Integer, default=0)
    NumberOfEmployees: Mapped[int] = mapped_column(Integer, default=0)
    ContractAmount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    ContractTotalPayments: Mapped[float | None] = mapped_column(Numeric(14, 2))
    ContractBalanceOwed: Mapped[float | None] = mapped_column(Numeric(14, 2))
    CustomerContact: Mapped[str | None] = mapped_column(String(100))
    CustomerPhone: Mapped[str | None] = mapped_column(String(30))
    CustomerEmail: Mapped[str | None] = mapped_column(String(120))
    ParentProjectID: Mapped[int | None] = mapped_column(ForeignKey("tblProject.ProjectID"))
    ProjectEntryUserName: Mapped[str | None] = mapped_column(String(50))
    ProjectEntryTimestamp: Mapped[datetime] = mapped_column(DateTime, default=now)

    customer: Mapped[Customer] = relationship(back_populates="projects")
    status: Mapped[PullDownProjStatus | None] = relationship()
    wcc: Mapped[PullDownWCC | None] = relationship()
    tracking: Mapped[list[Tracking]] = relationship(back_populates="project")


# --------------------------------------------------------------------------
# Tracking - a weekly assignment of an employee to a customer project
# --------------------------------------------------------------------------
class Tracking(Base):
    __tablename__ = "tblTracking"
    TrackingID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CustomerID: Mapped[int] = mapped_column(ForeignKey("tblCustomer.CustomerID"))
    EmployeeID: Mapped[int] = mapped_column(ForeignKey("tblEmployee.EmployeeID"))
    ProjectID: Mapped[int] = mapped_column(ForeignKey("tblProject.ProjectID"))
    AssignWeek: Mapped[int] = mapped_column(Integer)
    AssignYear: Mapped[int] = mapped_column(Integer)
    WeekEndingDate: Mapped[date] = mapped_column(Date)
    PayrollCoOnSiteID: Mapped[int | None] = mapped_column(
        ForeignKey("tblPullDownPayrollCoOnSite.PullDownPayrollCoOnSiteID")
    )
    PayRate: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    OTPayRate: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    BillRate: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    BillRateOT: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    SatHours: Mapped[float] = mapped_column(Float, default=0)
    SunHours: Mapped[float] = mapped_column(Float, default=0)
    MonHours: Mapped[float] = mapped_column(Float, default=0)
    TueHours: Mapped[float] = mapped_column(Float, default=0)
    WedHours: Mapped[float] = mapped_column(Float, default=0)
    ThuHours: Mapped[float] = mapped_column(Float, default=0)
    FriHours: Mapped[float] = mapped_column(Float, default=0)
    MonStatusFlagID: Mapped[int | None] = mapped_column(ForeignKey("tblPullDownStatusFlag.PullDownStatusFlagID"))
    TotalHours: Mapped[float] = mapped_column(Float, default=0)
    RegularHours: Mapped[float] = mapped_column(Float, default=0)
    OvertimeHours: Mapped[float] = mapped_column(Float, default=0)
    InvoiceAmount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    EmGrossPayroll: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    CalcProfitMargin: Mapped[float | None] = mapped_column(Float)
    WCC: Mapped[str | None] = mapped_column(String(20))
    Grade: Mapped[str | None] = mapped_column(String(5))
    HoursNote: Mapped[str | None] = mapped_column(Text)
    DirectionsSentEmail: Mapped[bool] = mapped_column(Boolean, default=False)
    DirectionsSentText: Mapped[bool] = mapped_column(Boolean, default=False)
    DirVerified: Mapped[bool] = mapped_column(Boolean, default=False)
    PayrollInfoSent: Mapped[bool] = mapped_column(Boolean, default=False)
    Placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    AssignmentUserName: Mapped[str | None] = mapped_column(String(50))
    AssignmentTimestamp: Mapped[datetime] = mapped_column(DateTime, default=now)

    customer: Mapped[Customer] = relationship()
    employee: Mapped[Employee] = relationship()
    project: Mapped[Project] = relationship(back_populates="tracking")
    payroll_co_on_site: Mapped[PullDownPayrollCoOnSite | None] = relationship()

    def recompute(self) -> None:
        """Mirror the Access/SQL calculated fields."""
        total = sum(
            float(x or 0)
            for x in (self.SatHours, self.SunHours, self.MonHours, self.TueHours, self.WedHours, self.ThuHours, self.FriHours)
        )
        self.TotalHours = round(total, 2)
        self.RegularHours = round(min(total, 40.0), 2)
        self.OvertimeHours = round(max(total - 40.0, 0.0), 2)
        pay = float(self.PayRate or 0)
        ot_pay = float(self.OTPayRate or pay * 1.5)
        bill = float(self.BillRate or 0)
        ot_bill = float(self.BillRateOT or bill * 1.5)
        self.EmGrossPayroll = round(self.RegularHours * pay + self.OvertimeHours * ot_pay, 2)
        self.InvoiceAmount = round(self.RegularHours * bill + self.OvertimeHours * ot_bill, 2)
        if self.InvoiceAmount:
            self.CalcProfitMargin = round((self.InvoiceAmount - self.EmGrossPayroll) / self.InvoiceAmount, 4)
        else:
            self.CalcProfitMargin = None
