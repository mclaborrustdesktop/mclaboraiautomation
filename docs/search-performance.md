# Search performance (2026-11-20, SQL Server section added 2026-11-23)

The real database is large: 178,993 employees, 106,828 customers, 192,225 weekly tracking rows, 15,748 jobs
(counted on the restored copy). The demo has 170 employees. Before this change every search loaded all matching
records into the web server's memory and sorted them there.

## On SQL Server: why word searches took 1.3 to 5 seconds, and what changed (2026-11-23)

Measured read-only on the restored copy with the website's restricted login, one search at a time. Scripts:
`tools\staging\search_diag.py` (the same search written in different ways), `search_timing.py` (the website's own
search code, before and after), `search_equivalence.py` (proof that the new statements return the same rows and
counts). All three run through `tools\staging\run-readonly.ps1`, which leaves the website in DEMO. Reports are in
`tools\prod-check\reports\search-diag-*`, `search-timing-*`, `search-equivalence-*`. Execution plans could not be
read: the restricted login has no SHOWPLAN permission (correct; it should not).

What the copy has: indexes on `tblEmployee` for `EmFirstName`, `EmLastName`, `EmMiddle` only; `tblCustomer` and
`tblCustomerContacts` have nothing but their primary keys; the note columns (`EmAdminNotes`, `EmSalesNotes`,
`CustomerNote`, `InvoiceNote`, `CustEmail`, the three job notes) are `nvarchar(max)`.

Where the time went, employee search for one word (medians):

| Statement | Time |
|---|---|
| Scan the whole 254-column table, one non-indexed column compared | 0.06 s |
| First + last name only (index scans) | 0.24 s |
| All ten text/phone columns, **without** the two lookup sub-selects | 0.40 s |
| All ten columns **with** the sub-selects `EmTradeID IN (SELECT ... WHERE PullDownTrade LIKE ...)` and the same for qualification | 1.09 s |
| The above plus ranking, the years-in-trade sort and paging (the website's statement) | 1.12 s |
| Two words instead of one | about double |

So the table scan itself was never the problem. Two thirds of each word search went into the two lookup
sub-selects: inside an `OR`, SQL Server evaluates them once per employee row (179,000 times each) instead of once.
Customers had the same pattern with the contact-name sub-select on `tblCustomerContacts` (0.8 s inside the OR, 0.18 s
on its own), plus 0.5 s for the three `nvarchar(max)` columns and 0.3 s for the phone-digit `REPLACE` chain. The
ranking sort cost 0.5 s only when tens of thousands of rows matched ("electric" = 74,699). Evaluating the match
once with CROSS APPLY would have saved 0.4 s on such searches but gained nothing elsewhere and is not expressible
in the ORM, so it was not done.

Changes made in the application (no index, no database change, same rows and counts - proven by
`search_equivalence.py`):

1. **Lookup matches are resolved first.** The trade and qualification names (32 and a few dozen rows), the contact
   names (one pass over the contacts table on its own) and, for jobs, the WCC and city lookups are matched in a
   separate small statement; the matching ids are written into the search statement as a plain `IN (3, 7)` list.
   When no lookup row matches, that branch of the OR is left out. Lists longer than 2,000 ids fall back to the
   sub-select, so the statement can never exceed SQL Server's parameter limit.
2. **Filter counts in one pass.** The five (employees) or six (customers) filter-count groups of the AI search page
   were five or six passes over the table, each repeating the search condition. On SQL Server they are now one
   `GROUPING SETS` pass; the ids are turned into labels from the small lookup tables in the application. (SQLite in
   the demo keeps the per-group statements; it has no GROUPING SETS.)
3. **Result ids are remembered for 30 seconds** (staging / production only, where the counts cache already was):
   the ordered ids of the first 2,000 matches of a search. Page 2, or the same search again, then reads only the 50
   records of the page. Ids are integers, never records; the memory is bounded (256 searches x 2,000 ids, about
   4 MB) and cleared like the counts cache.
4. **Digit searches** ("617") compare the phone columns once, with punctuation removed, instead of twice.

5. **Filters are written the same way.** A filter such as trade = Plumber used to be a sub-select too. Written as
   `EmTradeID IN (7)`, SQL Server applies it before the keyword comparisons; as a sub-select it let the comparisons
   run over every row first (a filtered word search: 0.78 s as a sub-select, 0.07 s as a literal). The previous
   shape of "active customers with active jobs" plus a word even exceeded the 20-second statement limit; the new
   shape answers in about a second.

Before and after, the website's own search code, one search at a time, median of 3 (`search-timing-baseline-*`
and `search-timing-after-20261123-095055`):

| Search | Before | After |
|---|---|---|
| Employees, first page by name (176,215) | 0.69 s | 0.67 s |
| Employees, word "smith" (1,021) | 1.30 s | 0.57 s |
| Employees, words "john smith" (6,308) | 2.19 s | 0.98 s |
| Employees, word "electric" (74,699, also matches the trade) | 1.96 s | 1.25 s |
| Employees, word in notes "foreman" (19) | 1.19 s | 0.61 s |
| Employees, phone digits "617" | 1.19 s | 0.47 s |
| Employees, "smith" page 2, cold | 1.39 s | 0.56 s |
| Employees, "smith" page 2 right after page 1 | 1.39 s | 0.11 s |
| Employees, trade filter + "smith" (475) | 0.92 s | 0.37 s |
| AI: "licensed electricians" with filter counts (21,611) | 1.61 s | 0.82 s |
| AI: "available plumbers with 5+ years experience" with counts (81) | 0.54 s | 0.26 s |
| Customers, first page by name (106,828) | 0.41 s | 0.39 s |
| Customers, word "electric" (11,486) | 2.67 s | 1.64 s |
| Customers, words "harbor electric" (11,596) | 5.01 s | 3.22 s |
| Customers, phone digits "617" (9,183) | 2.61 s | 2.34 s |
| AI: "customers in MA with active jobs" with counts (1,408) | 0.17 s | 0.14 s |
| Jobs, word "school" (294) | 0.34 s | 0.29 s |
| AI: "active jobs in MA not manned" with counts | 0.32 s | 0.37 s |
| Weekly tracking, newest 50 (192,225) | 0.42 s | 0.43 s |
| **Sum of the 18 medians** | **24.9 s** | **15.5 s** |

The filter-count passes alone (the part of every AI search page that repeats the search condition) went from 2.6 to
3.5 s to 0.4 to 0.7 s for employees and from 9 to 20 s to 0.9 to 2.6 s for customers (`search-equivalence-*`).
Every comparison in that report returned identical ids, totals and filter counts.

What this does not change: the per-row cost of `LIKE '%word%'` on ten columns, which is now the whole cost of a
customer word search (the customer table has no index besides its key, and three of its searched columns are
`nvarchar(max)`). If 30 people searching at once is still too slow after the next load test, the next step is a
database change needing approval: a full-text index on the name and note columns, or at least the narrow indexes
listed below.

### Many people at once, after the changes (2026-11-23)

`tools\staging\loadtest-staging.ps1` starts a second backend on port 8001 with the staging settings (4 worker
processes, restricted read-only login) and runs `loadtest.py` against it, so the DEMO website on port 8000 is not
touched. Each simulated person runs 6 searches from a mix of 12 (list pages, filters, name and word searches,
weekly tracking), one every 2 to 6 seconds. Reports: `tools\prod-check\reports\loadtest-*.txt`.

| Load | Searches | Not answered | Typical | 95% within | Slowest |
|---|---|---|---|---|---|
| Pilot 2026-11-20, 35 people, before the changes | 210 | 6 | 1.80 s | 12.87 s | 60.0 s |
| 35 people, after the changes | 210 | 0 | 0.23 s | 3.50 s | 6.3 s |
| 60 people, after the changes | 360 | 0 | 0.23 s | 8.11 s | 14.1 s |
| 60 people, 3 searches at once per process instead of 8 (`MAX_CONCURRENT_SEARCHES=3`) | 360 | 0 | 0.30 s | 7.14 s | 13.3 s |

The last row tried queueing searches earlier instead of letting 32 run at once on 4 cores: the tail shortens by
about a second and the typical search slows slightly, so the default of 8 per process stays.

Reading: with 35 people the website now answers everyone, typically in a quarter of a second (repeated searches
come from the 30-second memory, filtered lists in well under a second), and the slowest one in twenty takes 3.5 s.
With 60 people nobody is refused, but the slowest one in twenty waits 8 s and the slowest of all 14 s: that is
SQL Server Express's four processor cores being shared by many word searches at once. The word searches
(customers "electric", employees "john smith") are the ones at the tail; the indexes and full-text proposal
below are what would shorten it further.

### The remaining slow searches: customers (reviewed 2026-11-23)

Where a customer word search spends its time now (one word, 106,828 rows, from `search-diag-20261123-093301`):

| Part of the statement | Cost |
|---|---|
| Business name alone | 0.17 s |
| The seven other `nvarchar(255)` columns (city, ZIP, street, industry, description, phone) | about 0.5 s |
| The three `nvarchar(max)` columns `CustEmail`, `CustomerNote`, `InvoiceNote` (stored off-row) | about 0.5 s |
| The phone-digit `REPLACE` chain (digit searches only) | about 0.3 s |
| Contact names (now a separate pass over 187,636 contacts) | 0.2 s |
| A second word | the same again |

Every part is a comparison SQL Server has to make on every row; the application has no cheaper way to ask the
same question. A further application-side change was made in the 2026-11-23 afternoon build: with one search word
the ranking no longer re-evaluates the match (every row that passed the WHERE matched it), only the "starts a
name" bonus. The options that remain are database changes, both written as proposals and **not run**:

| Option | File | Gain | Catch |
|---|---|---|---|
| Full-text index on the searched name/address/note columns of customers, contacts, employees and jobs | `tools\prod-check\proposed-fulltext.sql` | Word searches become index look-ups (milliseconds instead of 1 to 3 s), and the CPU per search drops by the same amount, which is what 30 users need | Full-text search is **not installed** on the copy's instance (`SERVERPROPERTY('IsFullTextInstalled') = 0`, plain Express edition). Adding it means re-running SQL Server setup or another edition. Full-text finds words and prefixes, not fragments inside words; the owner must accept that |
| Narrow indexes for the filters that still scan: licenses by employee, tracking by employee/week/job, jobs by customer/status, customer status/type/rep/location, contacts by customer, employee trade/status/location | `tools\prod-check\proposed-indexes.sql` | "licensed" filter 0.5-0.9 s to milliseconds; tracking and dashboard queries; filtered customer lists | None for word searches. Each index slightly slows Access saves; add one at a time with timings before and after |
| A persisted computed column holding the phone digits, with an index | not written | Phone searches without the `REPLACE` chain | A new column on a production table; still a scan for `'%617%'` unless searches become "starts with" |

Recommendation: ask the administrator to confirm `IsFullTextInstalled` on the **live** server once it is known
(it may differ from the copy). If it is 0 there too, the realistic path for 30 users is the narrow indexes plus
keeping word searches as they are, which the load test below puts in numbers.

### The 30-second memory of results, reviewed for security (2026-11-23)

What is remembered (`search.py`, `_result_cache` and `_ids_cache`): for one exact search (environment, database,
entity, filters, words, sort) the total, the filter-count labels and numbers, and the ordered ids of the first
2,000 matches. Never a record, never a name or phone number. Records are read from the database on every request.

| Question | Answer |
|---|---|
| Can a user see another user's results? | Only what they could have asked for themselves. The memory is shared by everyone in one environment, which is correct because every user who may open the page sees the same records (there is no per-person row filtering in the McLabor data). Authorization runs **before** the memory is consulted: a person without `employees.view`, or not on the access lists, gets 403 and no search runs. Tested in `test_search_memory_never_bypasses_authorization_and_forgets_after_a_change` |
| Can DEMO results leak into STAGING, or STAGING into PRODUCTION? | No. The key starts with the environment and the database address, and each backend process serves one environment |
| Is anything personal stored? | Ids and totals, plus filter labels (trade and status names, city names, sales-rep names from the lookup table). The memory lives in the backend process only and is never written to disk or sent to the browser as such |
| Can a result be stale? | For up to 30 seconds in staging and production, where the website is read-only: an Access user's change in that window is not yet counted. A record deleted in that window drops off the page silently; a new one appears after 30 seconds. In the demo the memory is off (counts are exact immediately). Any successful change made **through the website** empties the memory at once (middleware in `main.py`), so this stays true if writes are ever approved |
| Bounded? | 1,024 remembered count/label entries and 256 remembered id lists of at most 2,000 integers: a few megabytes per process, oldest entries dropped first |
| Per process | Four backend processes each keep their own memory; a search repeated on another process scans again. Harmless, only less effective |

## What changed

All filtering, keyword matching, ranking, counting and paging now happen inside the database. One search runs a
small fixed number of statements and never returns more than one page of records.

| Area | Before | Now |
|---|---|---|
| Employee, customer, job search | Loaded every matching row, ranked in Python, then sliced a page | One statement returns the page's ids and the total; a second loads those 50 records |
| Keyword search (name, city, ZIP, e-mail, phone, notes) | Compared in Python against every loaded row | `LIKE` conditions with bound parameters; matches ranked by the database |
| "Last week worked" on employee results | Grouped the whole tracking table on every search | Only for the employees on the page |
| Customer "active jobs" filter and job counts | Loaded every customer's jobs | A database condition; counts fetched only for the page |
| Job results "crew assigned" | Loaded every tracking row of every job | Counted in the database for the page's jobs |
| Weekly tracking list and its search box | Loaded all rows, filtered in Python | Filtered and paged in the database |
| AI question parser | Loaded all 106,828 customer names on every question | Small lookups cached for 10 minutes; one bounded query finds a customer named in the question |
| Filter counts (facets) on the AI search page | Counted in Python over all loaded rows | `GROUP BY` in the database, first page only, top 8 values each |
| Job record page | Loaded the job's entire tracking history | Newest 60 assignments |

Limits now enforced: 50 records per page by default; at most 200 (100 on the AI search, 500 for the weekly tracking
grid); paging stops after the first 10,000 results with a message to narrow the search; at most 8 keywords; each SQL
Server statement is cancelled after 20 seconds; at most 8 searches run at once per server process (the site runs 4
processes), others wait up to 12 seconds and then get "many people are searching, try again".

New filter: ZIP code (`zip 02118`, `in 02118`) for employees, customers and jobs.

Unchanged: natural-language questions, trade synonyms ("pipe fitters", "sheet metal workers"), the "why it
matches" reasons, the approved table and column list (33 tables, 288 columns), and the separation of DEMO, STAGING
and PRODUCTION. Every result row comes from a database query; the question parser only produces filters and keywords.

## Measurements

Synthetic data of the real size (179,163 employees, 106,892 customers, 15,843 jobs, 193,172 tracking rows) in
SQLite, on this PC, with **no indexes other than primary keys**. Built by `python -m app.scaledata`.

One search at a time (`python -m app.searchbench`, median of 3):

| Search | Matches | Time | Records loaded |
|---|---|---|---|
| Employees, first page, no filter | 177,388 | 0.28 s | 68 |
| Employee by last name | 1,574 | 0.24 s | 59 |
| Employee by first and last name | 3,283 | 0.35 s | 65 |
| Trade + state | 5,123 | 0.15 s | 61 |
| Trade + city + licensed + 5 years | 152 | 0.17 s | 85 |
| ZIP prefix | 3,019 | 0.12 s | 66 |
| Phone digits | 2 | 0.62 s | 2 |
| Word in notes | 19,146 | 0.30 s | 61 |
| Page 100 of a large result | 65,280 | 0.24 s | 62 |
| AI question with filter counts | 75 to 228 | 0.68 to 0.74 s | 58 to 69 |
| Customers by name | 17,393 | 0.29 s | 69 |
| Customers with active jobs in a state | 1,144 | 0.04 s | 79 |
| Jobs by site name | 1,263 | 0.10 s | 100 |
| Tracking, one week | 802 | 0.05 s | 131 |

"Records loaded" is the page plus the lookups it links to. Memory used by all 22 benchmark searches run in a row:
under 1 MB.

Through the real web server (4 processes), many users at once:

| Load | Requests | Errors | Typical | 95% within | Slowest |
|---|---|---|---|---|---|
| 35 people, a search every 2 to 6 seconds | 280 | 0 | 0.30 s | 1.4 s | 3.0 s |
| 60 people, same pace | 360 | 0 | 0.49 s | 1.5 s | 2.8 s |
| Stress: 35 people with no pause at all | 175 | 0 | 1.8 s | 6.4 s | 8.3 s |

## What these numbers do and do not show

- They prove the design: work per search is bounded and 35 or more people can search at once.
- They are **not** SQL Server timings. The real `tblEmployee` has 254 columns, so a full pass over it reads far more
  data than the synthetic table. SQL Server Express also uses at most about 1.4 GB of memory and 4 processor cores.
- The real timings come from `python -m app.livecheck` on the staging copy, once the certificate and read-only
  login exist. It prints counts and timings only.
- The search assumes the database uses a case-insensitive collation (the SQL Server default). The live search test
  reports the collation and warns if it is case-sensitive.

## Indexes worth considering (none created; needs the owner's approval)

Which indexes exist today is unknown. `tools/prod-check/list-indexes.sql` lists them (read-only). Compare its
output with this table before proposing anything; an index that already exists must not be duplicated.

| Table | Columns | Helps |
|---|---|---|
| `tblEmployee` | `EmLastName, EmFirstName` | Name sort and "starts with" name lookups, duplicate check |
| `tblEmployee` | `EmState, EmCity` | State and city filters |
| `tblEmployee` | `EmTradeID` (also `SubTrade1ID`, `SubTrade2ID`) | Trade filter |
| `tblEmployee` | `EmZip` | ZIP filter |
| `tblEmployee` | `EmEmployeeStatusID` | Status filter |
| `tblEmployee` | `EmEmail` | Duplicate check |
| `tblEmployeeB` | `EmployeeID` | Will-travel lookup per employee |
| `tblEmployeeLicenses` | `EmployeeID, EmployeeLicenseExpDate` | Licensed and license-expiring filters |
| `tblCustomer` | `CustBusName` | Name sort, duplicate check |
| `tblCustomer` | `State, City` and `Zip` | Location filters |
| `tblCustomer` | `CustStatusID`, `CustomerTypeID`, `SalesmanID` | Status, type and sales-rep filters |
| `tblCustomerContacts` | `CustomerID` | Contact-name search |
| `tblProject` | `CustomerID` | Jobs per customer, active-jobs filter |
| `tblProject` | `ProjStatusID`, `SiteStateCityID`, `StartDate` | Status, location and start-date filters |
| `tblTracking` | `EmployeeID, WeekEndingDate` | Last week worked, an employee's history |
| `tblTracking` | `ProjectID` | Crew counts, a job's assignments |
| `tblTracking` | `WeekEndingDate` | The weekly grid |
| `tblTracking` | `CustomerID` | Tracking by customer |

Notes:

- A search for a word **inside** a name or a note (`LIKE '%word%'`) cannot use an ordinary index. If those searches
  are slow on SQL Server, the option is a full-text index on the name and note columns. That is a larger change.
- Narrow indexes matter more than usual here because the employee table is so wide.
- Each index slightly slows saving in Access and uses disk space. Add only the ones the live search test shows to
  be needed, one at a time, with the timings before and after.
- Years in trade is stored as a lookup label in the real database, so "5+ years" filters and sorting by experience
  cannot use an index.

## How to repeat

```
cd backend
.venv\Scripts\python.exe -m app.scaledata C:\temp\scale.db          (about 25 seconds, 93 MB)
.venv\Scripts\python.exe -m app.searchbench C:\temp\scale.db 35
.venv\Scripts\python.exe -m pytest tests\test_search_scale.py
```
