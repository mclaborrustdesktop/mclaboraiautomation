"""The synthetic McLabor-shaped database for the cloud staging rehearsal: production shape, invented data, guarded."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateTable

from app import synthdb


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    path = tmp_path_factory.mktemp("synth") / "synthetic.db"
    url = f"sqlite:///{path.as_posix()}"
    counts = synthdb.build(url, scale=0.01, quiet=True)
    engine = create_engine(url, future=True)
    yield url, counts, engine
    engine.dispose()


def test_all_33_tables_exist_in_production_shape(built):
    url, counts, engine = built
    names = set(inspect(engine).get_table_names())
    assert len(names) == 33 and {"tblEmployee", "tblEmployeeB", "tblPullDownYearsInTrade", "tblTracking", "tblOfficeStaff"} <= names
    cols = {c["name"] for c in inspect(engine).get_columns("tblEmployee")}
    assert "YearsInTradeID" in cols and "YearsInTrade" not in cols          # production shape, not the demo's convenience column
    assert "WillTravel" not in cols and "WillTravel" in {c["name"] for c in inspect(engine).get_columns("tblEmployeeB")}
    assert "SiteCity" not in {c["name"] for c in inspect(engine).get_columns("tblProject")} and "SiteStateCityID" in {c["name"] for c in inspect(engine).get_columns("tblProject")}
    assert {"SSNum", "EmDOB", "BankAccountNumber", "USCitizen"} <= cols     # restricted columns exist (empty) so the grants script applies


def test_rows_are_invented_and_consistent(built):
    url, counts, engine = built
    assert counts["tblEmployee"] >= 1789 and counts["tblCustomer"] >= 1068 and counts["tblProject"] >= 157 and counts["tblTracking"] >= 1922
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM tblEmployee WHERE SSNum IS NOT NULL OR EmDOB IS NOT NULL OR BankAccountNumber IS NOT NULL")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM tblEmployee e LEFT JOIN tblPullDownTrade t ON t.PullDownTradeID = e.EmTradeID WHERE t.PullDownTradeID IS NULL")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM tblTracking x LEFT JOIN tblProject p ON p.ProjectID = x.ProjectID WHERE p.ProjectID IS NULL OR p.CustomerID <> x.CustomerID")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM tblEmployeeB b LEFT JOIN tblEmployee e ON e.EmployeeID = b.EmployeeID WHERE e.EmployeeID IS NULL")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM tblEmployee WHERE EmEmail NOT LIKE '%@example.com'")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM tblOfficeStaff WHERE OfficeStaffPassword IS NOT NULL")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(DISTINCT PullDownCustomerType) FROM tblPullDownCustomerTypes")).scalar_one() == 7
        assert c.execute(text("SELECT COUNT(*) FROM tblEmployee WHERE EmMobilePhone IS NOT NULL")).scalar_one() == counts["tblEmployee"]  # contact columns filled, unlike the restored copy


def test_sql_server_ddl_compiles_with_identity_keys_and_foreign_keys():
    md = synthdb.build_metadata()
    emp = md.tables["tblEmployee"]
    ddl = str(CreateTable(emp).compile(dialect=mssql.dialect()))
    assert "[EmployeeID] INTEGER NOT NULL IDENTITY" in ddl and "PRIMARY KEY ([EmployeeID])" in ddl
    assert "FOREIGN KEY([EmTradeID]) REFERENCES [tblPullDownTrade] ([PullDownTradeID])" in ddl
    assert "[EmAdminNotes] VARCHAR(max)" in ddl or "[EmAdminNotes] TEXT" in ddl
    assert "[BaseSalary] NUMERIC(19, 4)" in ddl and "[EmployeeDuplicate] BIT" in ddl


def test_refuses_the_office_servers_and_existing_tables(built, monkeypatch):
    url, counts, engine = built
    monkeypatch.setattr(synthdb.settings, "office_hosts", "live-host, copy-host, 198.51.100.2")  # the real names live outside the code
    for host in ("LIVE-HOST,1433", "live-host\\SQLEXPRESS", "198.51.100.2", "COPY-HOST\\SQLEXPRESS", "localhost"):
        with pytest.raises(RuntimeError, match="never touched"):
            synthdb.refuse_office_servers(f"mssql+pyodbc://u:p@{host}/McLabor?driver=x")
    synthdb.refuse_office_servers("mssql+pyodbc://u:p@vm-mclabor-sql.internal,1433/McLaborSynthetic?driver=x")  # a cloud VM is fine
    with pytest.raises(RuntimeError, match="already exist"):
        synthdb.build(url, scale=0.01, quiet=True)
