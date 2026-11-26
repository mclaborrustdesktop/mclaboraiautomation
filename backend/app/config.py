"""Application settings.

All values can be overridden with environment variables or a `.env` file in
the backend folder.  DATA_SOURCE selects one of three environments (demo, staging,
production); see the Environment section below and docs/environments.md.
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Columns the web app must never request from the production SQL Server.  In production
# mode they are not mapped at all, so no SQL statement can mention them (models.py).
RESTRICTED_FIELDS: dict[str, tuple[str, ...]] = {
    "tblEmployee": ("EmDOB", "USCitizen", "I9Complete"),
    "tblOfficeStaff": ("OfficeStaffPassword",),
}


ENVIRONMENTS = ("demo", "staging", "production")


def _secrets_dir() -> str | None:
    """Container hosting: a directory of one-file-per-secret (Docker/Compose secrets, Azure Key Vault mounts).
    A file named like a setting (e.g. production_db_password, jwt_secret, gateway_secret) supplies that value, so
    no secret has to be in an environment variable or a settings file."""
    d = os.environ.get("MCLABOR_SECRETS_DIR")
    return d if d and Path(d).is_dir() else None


def _settings_file():
    """Which settings file to read: MCLABOR_SETTINGS_FILE (a service installed by deploy/vm keeps its env file outside the
    code folder), else backend/.env, else none (MCLABOR_ENV_FILE=none: the automated tests ignore the real backend/.env)."""
    explicit = os.environ.get("MCLABOR_SETTINGS_FILE")
    if explicit:
        return explicit
    return None if os.environ.get("MCLABOR_ENV_FILE") == "none" else BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_settings_file(), extra="ignore", secrets_dir=_secrets_dir())

    app_name: str = "MC Labor AI Automation"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'mclabor_demo.db').as_posix()}"
    jwt_secret: str = "change-me-in-production-mc-labor-demo-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    seed_on_startup: bool = True
    demo_password: str = "mclabor2025"
    # AI search. If ANTHROPIC_API_KEY is present the Claude API is used to
    # interpret natural-language searches; otherwise a built-in heuristic
    # parser is used so the demo works fully offline.
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"

    # ---- Environment -------------------------------------------------------
    # DATA_SOURCE selects exactly one environment. Each has its own server settings, its own
    # web sign-in file and its own write switch, so one can never borrow another's settings.
    #   demo        local SQLite file with synthetic data (default)
    #   staging     a RESTORED COPY of the McLabor database on SQL Server (for testing; real data, not live)
    #   production  the LIVE McLabor database on SQL Server
    # Staging and production are read-only unless that environment's own *_WRITES_ENABLED=true AND
    # *_WRITE_APPROVAL reference are set.
    data_source: str = "demo"

    # ---- PostgreSQL (the cloud database that replaces SQL Server when Access is retired; deploy/railway) ----
    # When an environment has a *_DATABASE_URL (postgresql+psycopg://...), it uses that PostgreSQL database and its
    # SQL Server settings are ignored. The database is the company's own: read-write, no SQL Server write switch.
    #   demo        DATABASE_URL (sqlite by default; a local PostgreSQL for development)
    #   staging     STAGING_DATABASE_URL     synthetic data only until the owner approves a migration
    #   production  PRODUCTION_DATABASE_URL  the migrated McLabor data, once the owner approves
    staging_database_url: str | None = None
    production_database_url: str | None = None
    # Table shape: "production" = the McLabor SQL Server structure (YearsInTradeID, tblEmployeeB.WillTravel,
    # SiteStateCityID; built by app.pgschema / app.synthdb); "demo" = the demo's convenience columns (create_all).
    # Default: production for SQL Server and for PostgreSQL in staging/production; demo otherwise.
    db_shape: str | None = None

    # ---- Search-only mirror fed by the office sync agent (docs/cloud/13-one-way-sync.md) ----
    # SITE_MODE "search-only": no record can be added, edited or deleted on the website, administrators included;
    # the office SQL Server + Access stay the primary system and the agent copies the approved tables here one way.
    # "full": the Add/Edit code is active (demo, and a future release). Default: search-only whenever the database
    # is a PostgreSQL mirror in staging/production, full otherwise.
    site_mode: str | None = None
    # The office sync agent proves itself with this key (32+ random characters, sealed in the hosting service). Unset =
    # the ingest endpoints do not exist. Never used with a SQL Server backend.
    sync_api_key: str | None = None
    # The website warns when the last successful sync is older than this (twice-daily runs: 14 hours).
    sync_stale_hours: int = 14
    sync_source_label: str = "the office McLabor system"
    # The ONLY source the ingest API accepts runs from, as the agent announces it: "<expected server name>/<database>" for
    # SQL Server, "sqlite (given)" for a synthetic file. Unset = the mirror still refuses a source different from the one
    # its earlier successful runs came from. Production sets it to the live server, so synthetic data can never land there.
    sync_expected_source: str | None = None

    # The office SQL Server hosts (names and addresses): never a PostgreSQL host, never a synthetic-data or schema
    # target, never a sync mirror. Kept OUT of the code: OFFICE_HOSTS=name1,addr1,... or one per line in
    # backend/office-hosts.txt (ignored by git). Set it on every office PC that runs the agent or the tools.
    office_hosts: str = ""

    staging_db_server: str | None = None  # e.g. COPY-HOST\\SQLEXPRESS
    staging_db_name: str = "McLabor"
    staging_db_expected_server_name: str | None = None  # what the server must call itself; checked on every connection
    staging_db_driver: str | None = None
    staging_db_trusted_connection: bool = False
    staging_db_user: str | None = None
    staging_db_password: str | None = None
    staging_db_encrypt: bool = True
    staging_db_trust_server_certificate: bool = False
    staging_writes_enabled: bool = False
    staging_write_approval: str | None = None

    production_db_server: str | None = None  # e.g. LIVE-HOST\\SQLEXPRESS
    production_db_name: str = "McLabor"
    production_db_expected_server_name: str | None = None
    production_db_driver: str | None = None  # default: newest installed "ODBC Driver NN for SQL Server"
    production_db_trusted_connection: bool = False  # Windows authentication instead of user/password
    production_db_user: str | None = None
    production_db_password: str | None = None  # set in backend/.env only - never committed, never logged
    production_db_encrypt: bool = True
    production_db_trust_server_certificate: bool = False
    production_writes_enabled: bool = False
    production_write_approval: str | None = None  # change-ticket / sign-off reference required to enable writes
    schema_csv_dir: str = str(BACKEND_DIR.parent / "docs" / "schema")

    # A single SQL statement is cancelled after this many seconds (staging / production), so one slow
    # search cannot tie up the server or a database connection.
    query_timeout_seconds: int = 20
    # Connections kept open to SQL Server per worker process (plus the same number of short-lived extras).
    db_pool_size: int = 10
    # How long the "number of matches" and the filter counts of a search are remembered, so that going to page 2
    # or repeating a search does not scan the tables again. Unset = 30 seconds with real data (staging/production,
    # which are read-only) and 0 in the demo, where records are edited and counts must be exact immediately.
    search_cache_seconds: int | None = None
    # Searches allowed to run at the same moment in ONE server process (there are normally 4 processes), and how long
    # a further search waits for a free slot before the user is told the system is busy.
    max_concurrent_searches: int = 8
    search_wait_seconds: int = 12

    # Web sign-in passwords live in their own local database, never in tblOfficeStaff (see webauth.py).
    # Each environment uses a DIFFERENT file by default, so passwords never carry over between them.
    web_auth_database_url: str | None = None
    # Website administrators while connected to real data (staging / production): initials or OfficeStaffID numbers,
    # separated by commas. In the real McLabor database nobody has the "Profile" flag and the permission table lists
    # Access forms, not website pages, so who may use the website is decided HERE, outside the business database.
    # Ignored in the demo.
    web_admins: str = ""
    # Website USERS with real data: may open employees, customers, jobs, weekly tracking and the AI search, but not
    # user management or the system status page, and can never change records. Same format as WEB_ADMINS.
    # A person on neither list is refused at sign-in and at the gateway, even with a web password. Ignored in the demo.
    web_users: str = ""
    # First sign-in on a fresh hosted deployment (no database shell needed): a sealed, one-time value accepted as the
    # password of the FIRST name in WEB_ADMINS while that person has no web password yet. It becomes their password
    # with "must change" set, so the first sign-in ends in choosing a real one; then remove this setting. It never
    # replaces an existing password and never applies to anyone else. 16+ characters, not the demo password.
    web_bootstrap_password: str | None = None
    # ---- ACCESS_MODE=passcode: one site password instead of a user name + password (docs/cloud/18-password-only-access.md) ----
    # The password exists only as this PBKDF2 hash (python -m app.webauth site-password prints it from a hidden prompt).
    # Never the plain password, never in the code, never logged.
    site_password_hash: str | None = None
    # A label for the secret in use: "initial" for the set-up password; production refuses to start with it (the owner
    # must rotate to a unique production secret and label it, e.g. "production-2026-12").
    site_password_label: str = "initial"
    # Who the person is behind the site password: the staff record named here (initials or e-mail), unless the request
    # carries a Cloudflare Access identity (certificate common name or e-mail), which always wins and is audited.
    site_default_user: str = ""
    site_session_minutes: int = 480          # an unlock lasts 8 hours, then the password screen returns
    site_lock_failures: int = 5              # per address, within site_lock_minutes
    site_lock_minutes: int = 15
    site_global_lock_failures: int = 50      # from all addresses together: everyone waits site_lock_minutes
    # ---- Approved devices (docs/cloud/18 section 2): the password AND a signature from the device's own authenticator ----
    site_device_approval: bool = False       # SITE_DEVICE_APPROVAL=true turns the boundary on (passcode mode only)
    webauthn_rp_id: str | None = None        # the website's host name, e.g. search.example.com (credentials are bound to it)
    webauthn_origin: str | None = None       # https://search.example.com
    site_device_limit: int = 40              # approved + pending devices (20 employees x 2 devices)
    # One-time, sealed: approves the FIRST device ever as SITE_DEFAULT_USER while no approved device exists; then delete it.
    site_device_bootstrap_code: str | None = None
    # With real data, administrators grant and remove website access in the website itself (Users page, or
    # `python -m app.webauth access-set`), stored in the web sign-in file - no restart, no redeploy. The lists above
    # are the bootstrap. The company's maximum number of website users (decision 2026-11-23: 20): the website refuses
    # to grant access beyond ACCESS_SEAT_LIMIT and warns from ACCESS_SEAT_WARN on. 0 = no limit.
    access_seat_limit: int = 20
    access_seat_warn: int = 16
    # The sign-in service in front (Cloudflare Zero Trust) counts website users AND the WARP users of the Access/
    # QuickBooks PCs against its free plan of 50. ACCESS_OTHER_SEATS = how many of those other users exist.
    access_service_limit: int = 50
    access_other_seats: int = 8
    # Claude is an outside service. With real data (staging / production) it may only be used after the owner has
    # approved it in writing; put the reference (ticket, e-mail date) here. Without it the built-in parser is used,
    # and the website refuses to start if ANTHROPIC_API_KEY is present. Never needed in the demo.
    claude_real_data_approval: str | None = None

    # ---- How people get in (see the `access` property and docs/access-without-login.md) ----
    #   open     DEMO only: no sign-in page, everyone is the demo administrator. Refused with real data.
    #   login    web sign-in page (initials + web password). The default for staging / production.
    #   gateway  no sign-in page; a company-only gateway (VPN + Zero Trust proxy) signs people in and tells this
    #            app who they are. Staging / production only, and only with GATEWAY_SECRET set.
    access_mode: str | None = None
    # A long random value known only to the gateway and this app. The gateway adds it to every request it forwards;
    # a request without it is refused. It never reaches the browser.
    gateway_secret: str | None = None
    gateway_secret_header: str = "X-Gateway-Secret"
    # The header in which the gateway puts the signed-in person's e-mail address
    # (Cloudflare Access: Cf-Access-Authenticated-User-Email; oauth2-proxy: X-Auth-Request-Email).
    gateway_email_header: str = "X-Auth-Request-Email"
    # Addresses the gateway's requests arrive from (the gateway runs on this PC, or on one known host). A request
    # carrying the gateway headers from any other address is refused even when the secret is right, so a forged
    # header can never be sent straight to the backend.
    gateway_trusted_proxies: str = "127.0.0.1,::1"
    # Which gateway names the person:
    #   proxy           the reverse proxy from deploy/gateway or deploy/cloud: shared secret + e-mail header (default)
    #   azure-easyauth  Azure Container Apps / App Service built-in authentication: the platform's own sidecar signs
    #                   the person in with Microsoft Entra ID, strips any X-MS-CLIENT-PRINCIPAL-* header a visitor sent,
    #                   and adds its own. There is no shared secret; the sidecar is the only way to reach the app.
    #   cloudflare-access  Cloudflare Access + Tunnel (deploy/vm): every request carries a Cf-Access-Jwt-Assertion token
    #                   signed by Cloudflare for this application; the backend verifies it (cloudflare_access.py).
    gateway_platform: str = "proxy"
    # Cloudflare Access: the team domain (e.g. mclabor.cloudflareaccess.com) and the application's AUD tag.
    cloudflare_access_team_domain: str | None = None
    cloudflare_access_aud: str | None = None

    # ---- hosting ----------------------------------------------------------
    # "json" writes one JSON object per log line (for a container log service); "text" for a terminal.
    log_format: str = "text"
    log_level: str = "INFO"
    # One line per request (method, path, status, duration, request id - never the query string, so never a search
    # word or a name). Off on this PC, on in containers.
    access_log: bool = False
    # Seconds to wait for a new database connection, and how often the ODBC driver retries a connection that a cloud
    # database dropped (transient errors are normal there).
    db_connect_timeout: int = 15
    db_connect_retries: int = 3

    # ---- which environment ---------------------------------------------------
    @property
    def environment(self) -> str:
        env = (self.data_source or "demo").strip().lower()
        if env not in ENVIRONMENTS:
            raise ValueError(f"DATA_SOURCE must be one of {', '.join(ENVIRONMENTS)} (got '{self.data_source}')")
        return env

    @property
    def is_demo(self) -> bool:
        return self.environment == "demo"

    @property
    def is_staging(self) -> bool:
        return self.environment == "staging"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_real_data(self) -> bool:
        """Staging and production, whatever the database engine: access lists apply, restricted columns are withheld,
        nothing is seeded, no outside AI service without approval. The demo is the only open environment."""
        return self.environment in ("staging", "production")

    @property
    def postgres_url(self) -> str | None:
        """The active environment's PostgreSQL URL, if it has one."""
        if self.is_demo:
            url = self.database_url
            return url if url.startswith(("postgresql", "postgres:")) else None
        return (getattr(self, f"{self.environment}_database_url") or "").strip() or None

    @property
    def db_backend(self) -> str:
        """'sqlite' | 'postgres' | 'sqlserver' for the active environment."""
        if self.postgres_url:
            return "postgres"
        if self.is_real_data:
            return "sqlserver"
        return "sqlite"

    @property
    def is_sql_server(self) -> bool:
        """True when the active environment talks to the McLabor SQL Server (staging copy or live)."""
        return self.db_backend == "sqlserver"

    @property
    def is_postgres(self) -> bool:
        return self.db_backend == "postgres"

    @property
    def production_shape(self) -> bool:
        """Do the tables have the McLabor SQL Server structure (as opposed to the demo's convenience columns)?"""
        shape = (self.db_shape or "").strip().lower()
        if shape in ("production", "demo"):
            return shape == "production"
        return self.db_backend == "sqlserver" or (self.db_backend == "postgres" and self.is_real_data)

    @property
    def supports_grouping_sets(self) -> bool:
        return self.db_backend in ("sqlserver", "postgres")

    @property
    def environment_label(self) -> str:
        base = {"demo": "DEMO - synthetic data", "staging": "STAGING - restored copy of real data", "production": "PRODUCTION - live data"}[self.environment]
        if self.is_postgres and self.is_staging:
            base = "STAGING - synthetic data on PostgreSQL"
        elif self.is_postgres and self.is_production:
            base = "PRODUCTION - PostgreSQL"
        return base

    # ---- the ACTIVE environment's own database settings ------------------------
    def _db(self, key: str):
        if not self.is_sql_server:
            return None
        return getattr(self, f"{self.environment}_db_{key}")

    @property
    def db_server(self) -> str | None:
        return self._db("server")

    @property
    def db_name(self) -> str:
        return self._db("name") or "McLabor"

    @property
    def db_expected_server_name(self) -> str | None:
        return self._db("expected_server_name")

    @property
    def db_driver(self) -> str | None:
        return self._db("driver")

    @property
    def db_trusted_connection(self) -> bool:
        return bool(self._db("trusted_connection"))

    @property
    def db_user(self) -> str | None:
        return self._db("user")

    @property
    def db_password(self) -> str | None:
        return self._db("password")

    @property
    def db_encrypt(self) -> bool:
        return bool(self._db("encrypt"))

    @property
    def db_trust_server_certificate(self) -> bool:
        return bool(self._db("trust_server_certificate"))

    @property
    def sql_writes_enabled(self) -> bool:
        return self.is_sql_server and bool(getattr(self, f"{self.environment}_writes_enabled"))

    @property
    def sql_write_approval(self) -> str:
        return (getattr(self, f"{self.environment}_write_approval") or "").strip() if self.is_sql_server else ""

    @property
    def sql_writes_allowed(self) -> bool:
        """Writes to the active SQL Server environment: needs that environment's switch AND approval reference."""
        return self.sql_writes_enabled and bool(self.sql_write_approval)

    @property
    def office_host_set(self) -> frozenset[str]:
        """Lower-case office host names/addresses from OFFICE_HOSTS and backend/office-hosts.txt (never in the code)."""
        names = {h.strip().lower() for h in (self.office_hosts or "").split(",") if h.strip()}
        f = BACKEND_DIR / "office-hosts.txt"
        if f.is_file():
            names |= {l.strip().lower() for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")}
        return frozenset(names)

    def is_office_host(self, host_or_url: str | None) -> bool:
        """Is this host name / address, or the host of this URL, one of the office servers? Only the host part counts:
        'LIVE-HOST\\SQLEXPRESS', 'live-host,1433', 'mssql+pyodbc://u:p@LIVE-HOST,1433/db' all mean LIVE-HOST; a file path
        or a database name that happens to contain a name does not."""
        s = (host_or_url or "").strip().lower()
        if "://" in s:
            s = s.split("://", 1)[1].split("/", 1)[0].rsplit("@", 1)[-1]  # the authority without credentials
        host = s.split("\\")[0].split(",")[0].split(":")[0].strip().strip("[]")
        return bool(host) and host in self.office_host_set

    @property
    def search_only(self) -> bool:
        """Is this website a read-only mirror of the office system (no Add/Edit/Delete for anyone)?"""
        mode = (self.site_mode or "").strip().lower()
        if mode in ("search-only", "search_only", "readonly", "read-only"):
            return True
        if mode == "full":
            return False
        return self.is_postgres and self.is_real_data

    @property
    def sync_enabled(self) -> bool:
        """Do the ingest endpoints for the office sync agent exist? Needs a key, and never with a SQL Server backend."""
        return bool((self.sync_api_key or "").strip()) and len((self.sync_api_key or "").strip()) >= 32 and not self.is_sql_server

    @property
    def writes_allowed(self) -> bool:
        """May the website change records? Demo and PostgreSQL (the company's own database): yes, unless the site is
        search-only. SQL Server: only with that environment's write switch and approval reference."""
        if self.search_only:
            return False
        return not self.is_sql_server or self.sql_writes_allowed

    @property
    def search_cache_ttl(self) -> int:
        if self.search_cache_seconds is not None:
            return max(0, self.search_cache_seconds)
        return 30 if self.is_sql_server else 0

    @property
    def web_auth_url(self) -> str:
        if self.web_auth_database_url:
            return self.web_auth_database_url
        name = {"demo": "web_auth.db", "staging": "web_auth_staging.db", "production": "web_auth_production.db"}[self.environment]
        return f"sqlite:///{(BACKEND_DIR / name).as_posix()}"

    @property
    def access(self) -> str:
        """'open', 'login', 'passcode' or 'gateway'. Real data can never be 'open', whatever the settings file says."""
        mode = (self.access_mode or "").strip().lower()
        if mode in ("gateway", "passcode"):
            return mode
        if self.is_real_data:
            return "login"
        return "login" if mode == "login" else "open"

    @staticmethod
    def _name_set(value: str) -> set[str]:
        return {a.strip().lower() for a in (value or "").split(",") if a.strip()}

    @property
    def web_admin_set(self) -> set[str]:
        return self._name_set(self.web_admins) if self.is_real_data else set()

    @property
    def web_user_set(self) -> set[str]:
        return self._name_set(self.web_users) if self.is_real_data else set()

    @property
    def gateway_trusted_proxy_set(self) -> set[str]:
        return self._name_set(self.gateway_trusted_proxies)

    def is_trusted_proxy(self, host: str | None) -> bool:
        """Did the request come from the gateway? Entries are addresses (127.0.0.1), networks (172.16.0.0/12: a container
        network) or, for the test client only, the literal name it reports. Anything unparsable never matches.
        "any" is accepted only with the cloudflare-access platform, where every request proves itself with a token
        signed by Cloudflare for this application (a hosted platform's own proxy is then the visible client)."""
        import ipaddress

        if "any" in self.gateway_trusted_proxy_set and (self.gateway_platform or "").strip().lower() == "cloudflare-access":
            return True
        host = (host or "").strip().lower()
        if not host:
            return False
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            return host in self.gateway_trusted_proxy_set  # a non-address client name (the test client)
        for entry in self.gateway_trusted_proxy_set:
            try:
                if "/" in entry:
                    if addr in ipaddress.ip_network(entry, strict=False):
                        return True
                elif addr == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                continue
        return False

    @property
    def claude_allowed(self) -> bool:
        """May questions be sent to the Claude API? Demo: whenever a key is set. Real data: only with the owner's approval on record."""
        if not self.anthropic_api_key:
            return False
        return not self.is_real_data or bool((self.claude_real_data_approval or "").strip())

    @property
    def restricted_field_names(self) -> list[str]:
        """Form/API field names that are hidden while connected to real data (staging or production)."""
        return [f for t in ("tblEmployee",) for f in RESTRICTED_FIELDS[t]] if self.is_real_data else []

    def environment_problems(self) -> list[str]:
        """Reasons the app must refuse to start in the selected environment."""
        p: list[str] = []
        if not self.is_real_data:
            return p
        E = self.environment.upper()
        if self.jwt_secret.startswith("change-me"):
            p.append("JWT_SECRET is still the demo value. Set a long random JWT_SECRET in backend/.env.")
        if self.is_postgres:
            url = self.postgres_url or ""
            if not url.startswith("postgresql"):
                p.append(f"{E}_DATABASE_URL must be a postgresql+psycopg:// URL.")
            if "sslmode=" not in url and ".railway.internal" not in url and "localhost" not in url and "127.0.0.1" not in url:
                p.append(f"{E}_DATABASE_URL must use TLS (sslmode=require) unless it is a private-network or local address.")
            if self.is_office_host(url):
                p.append(f"{E}_DATABASE_URL points at an office server; the office servers are never used as PostgreSQL hosts.")
        else:
            if not self.db_server:
                p.append(f"{E}_DB_SERVER is not set.")
            if not self.db_expected_server_name:
                p.append(f"{E}_DB_EXPECTED_SERVER_NAME is not set. It names the one server this environment may talk to.")
            if not self.db_encrypt:
                p.append(f"{E}_DB_ENCRYPT must stay true.")
        mode = (self.access_mode or "").strip().lower()
        if mode not in ("", "login", "gateway", "passcode"):
            p.append(f"ACCESS_MODE={mode} is not allowed with real data. Use 'login', 'passcode' or 'gateway'; anonymous access is refused.")
        if mode == "passcode":
            h = (self.site_password_hash or "").strip()
            if not h.startswith("pbkdf2$") or h.count("$") != 3:
                p.append("ACCESS_MODE=passcode needs SITE_PASSWORD_HASH: the PBKDF2 hash printed by `python -m app.webauth site-password` (never the password itself).")
            cf_identity = (self.gateway_platform or "").strip().lower() == "cloudflare-access" and bool((self.cloudflare_access_team_domain or "").strip()) and bool((self.cloudflare_access_aud or "").strip())
            if not (self.site_default_user or "").strip() and not cf_identity:
                p.append("ACCESS_MODE=passcode needs SITE_DEFAULT_USER (the staff record people act as) or a Cloudflare Access identity (GATEWAY_PLATFORM=cloudflare-access with team domain and AUD).")
            if self.environment == "production" and (self.site_password_label or "").strip().lower() in ("", "initial", "staging", "test", "demo"):
                p.append("Production needs its own site password: set a new SITE_PASSWORD_HASH and SITE_PASSWORD_LABEL (e.g. production-2026-12). The initial/staging password is refused.")
            if not 5 <= int(self.site_session_minutes) <= 720:
                p.append("SITE_SESSION_MINUTES must be between 5 and 720 (12 hours).")
            if self.site_device_approval:
                rp, org = (self.webauthn_rp_id or "").strip(), (self.webauthn_origin or "").strip()
                if not rp or not org.startswith("https://") or rp not in org:
                    p.append("SITE_DEVICE_APPROVAL=true needs WEBAUTHN_RP_ID (the website's host name) and WEBAUTHN_ORIGIN (https://<that host>).")
                if self.site_device_bootstrap_code and len(self.site_device_bootstrap_code.strip()) < 16:
                    p.append("SITE_DEVICE_BOOTSTRAP_CODE must be 16 or more characters (or unset).")
        elif self.site_device_approval:
            p.append("SITE_DEVICE_APPROVAL=true only applies with ACCESS_MODE=passcode.")
        platform = (self.gateway_platform or "proxy").strip().lower()
        if platform not in ("proxy", "azure-easyauth", "cloudflare-access"):
            p.append(f"GATEWAY_PLATFORM={platform} is not known. Use 'proxy', 'azure-easyauth' or 'cloudflare-access'.")
        if mode == "gateway" and platform == "proxy" and len(self.gateway_secret or "") < 32:
            p.append("ACCESS_MODE=gateway needs GATEWAY_SECRET (32 or more random characters) shared with the gateway.")
        if mode == "gateway" and platform == "cloudflare-access" and not ((self.cloudflare_access_team_domain or "").strip() and (self.cloudflare_access_aud or "").strip()):
            p.append("GATEWAY_PLATFORM=cloudflare-access needs CLOUDFLARE_ACCESS_TEAM_DOMAIN and CLOUDFLARE_ACCESS_AUD (the Access application's AUD tag).")
        if mode == "gateway" and not self.gateway_trusted_proxy_set:
            p.append("ACCESS_MODE=gateway needs GATEWAY_TRUSTED_PROXIES: the address(es) the gateway forwards from, e.g. 127.0.0.1.")
        if mode == "gateway" and "any" in self.gateway_trusted_proxy_set and platform != "cloudflare-access":
            p.append("GATEWAY_TRUSTED_PROXIES=any is only allowed with GATEWAY_PLATFORM=cloudflare-access (the signed token is the proof).")
        boot = (self.web_bootstrap_password or "").strip()
        if boot and (len(boot) < 16 or boot == self.demo_password or not (self.web_admins or "").strip()):
            p.append("WEB_BOOTSTRAP_PASSWORD must be 16 or more characters, not the demo password, and WEB_ADMINS must name the first administrator.")
        if self.anthropic_api_key and not (self.claude_real_data_approval or "").strip():
            p.append("ANTHROPIC_API_KEY is set, so questions about real data would go to an outside AI service. Remove the key, "
                     "or record the owner's written approval in CLAUDE_REAL_DATA_APPROVAL.")
        if self.is_sql_server and self.db_trust_server_certificate:
            p.append(f"{E}_DB_TRUST_SERVER_CERTIFICATE must stay false: the server certificate has to be verified.")
        if (self.sync_api_key or "").strip() and len((self.sync_api_key or "").strip()) < 32:
            p.append("SYNC_API_KEY must be at least 32 random characters.")
        if (self.sync_api_key or "").strip() and self.is_sql_server:
            p.append("SYNC_API_KEY is set but this environment uses SQL Server: the sync target is only ever the PostgreSQL mirror.")
        if self.is_postgres:
            s_url, p_url = (self.staging_database_url or "").strip().lower(), (self.production_database_url or "").strip().lower()
            if s_url and p_url and s_url == p_url:
                p.append("STAGING_DATABASE_URL and PRODUCTION_DATABASE_URL are the same database. They must be different.")
            return p

        def norm(v: str | None) -> str:
            return (v or "").strip().lower()

        # Staging and production must be two different places.
        s_exp, p_exp = norm(self.staging_db_expected_server_name), norm(self.production_db_expected_server_name)
        s_srv, p_srv = norm(self.staging_db_server), norm(self.production_db_server)
        same_db = norm(self.staging_db_name) == norm(self.production_db_name)
        if s_exp and p_exp and s_exp == p_exp and same_db:
            p.append("STAGING and PRODUCTION name the same server and database (EXPECTED_SERVER_NAME). They must be different.")
        if s_srv and p_srv and s_srv == p_srv and same_db:
            p.append("STAGING_DB_SERVER and PRODUCTION_DB_SERVER are the same server and database. They must be different.")
        other = "production" if self.is_staging else "staging"
        if norm(self.db_expected_server_name) and norm(self.db_expected_server_name) in (norm(getattr(self, f"{other}_db_server")),) and same_db:
            p.append(f"{E}_DB_EXPECTED_SERVER_NAME equals {other.upper()}_DB_SERVER. This looks like the wrong environment's server.")
        return p

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def security_warnings(self) -> list[str]:
        w = []
        if self.jwt_secret.startswith("change-me"):
            w.append("JWT_SECRET is the built-in demo value - set a long random secret before real users sign in.")
        if self.is_demo and self.seed_on_startup and self.demo_password == "mclabor2025":
            w.append("Demo accounts use the shared demo password - fine for the demo, not for real users.")
        if self.is_sql_server and not self.sql_writes_allowed:
            w.append(f"{self.environment.capitalize()} data source is READ-ONLY (writes not approved).")
        if self.is_real_data and not (self.web_admin_set or self.web_user_set):
            w.append("Nobody can use the website: WEB_ADMINS and WEB_USERS are both empty. Every sign-in and gateway request will be refused.")
        return w

settings = Settings()
