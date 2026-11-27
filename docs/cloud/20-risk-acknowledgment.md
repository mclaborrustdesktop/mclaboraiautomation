# 20. MC Labor search website: production security arrangement and risk acknowledgment (for the client's review)

Prepared 2026-11-27 for MC Labor Sources Inc. One page. Signing it is one of the three approvals needed before real
employee records are loaded (the other two: creating the production project on Railway, and the first data transfer).

## What the website is

A read-only search mirror of the office McLabor database, hosted on Railway (PostgreSQL + the website), refreshed
twice a day by an office agent that reads the live SQL Server with a dedicated read-only login. Nothing flows back to
the office; the website refuses every change to a business record (HTTP 423). The live SQL Server and the Access
application are untouched.

## How people get in (the arrangement chosen on 2026-11-27)

Open the website, enter the single **access password**, search. No user names, e-mails, codes, devices or
certificates. Any computer, browser or phone with the correct password is in, from anywhere.

Protections in force: HTTPS only (with HSTS); the password is stored only as a PBKDF2 hash in a sealed variable; wrong
attempts answer the same generic message; an address is locked for 15 minutes after 5 failures (doubling), and 50
failures across the site slow unknown addresses while known office addresses keep working; sessions last 8 hours;
every attempt is logged with address, browser, time and outcome; browser hardening headers (frame denial, content
security policy); the database and the backend have no public address; daily and weekly snapshots plus
point-in-time recovery; the production password is a new 20-character random secret (the staging one, which was
shared in writing, is refused by production).

## Risks that remain with a single shared password

| # | Risk | What limits it | What the client should do |
|---|---|---|---|
| 1 | One secret for everyone: a leaked or guessed password exposes every approved column of every record to its holder, from anywhere, until it is rotated | 20 random characters; lockout; rotation is one variable change and ends every session at once | Hand the password out in person or through the company password safe; rotate it when an employee leaves or on any suspicion |
| 2 | No individual identity: the log shows address, browser and time, never a person | Office PCs share a fixed office address, so office use is recognisable; outside use is only an address | Accept that misuse can be traced to an address and a time, not to a named employee; or add Cloudflare Access later |
| 3 | The password screen is reachable from the whole internet | Lockout stops fast guessing; a 20-character random password makes slow guessing hopeless | Optional later: Cloudflare Free in front with a rate-limit rule and the office-address rule (0 USD) |
| 4 | Phishing: a copied page could collect the password | Bookmark on office PCs; the real address uses HTTPS and the company name | Never send the address and the password in the same message; tell staff the site never asks for anything but the password |
| 5 | A signed-in browser left open stays in for up to 8 hours | Session expiry; lock-screen policy on PCs | Lock PCs when leaving; ask for a shorter session if wanted (5 minutes to 12 hours is configurable) |
| 6 | The 17 sensitive columns (SSN, bank, birth, I-9, W-4, ...) are never copied, but the 288 approved columns are company data outside the office | Read-only login that cannot see those columns at all; backups encrypted at rest by Railway; US region | Confirm the approved column list (`tools/prod-check/required_schema.json`) is what the company is willing to host |

Everyone who holds the password also sees the administrator pages (user list, status page, unlock log) if the shared
identity is listed in `WEB_ADMINS`; otherwise nobody sees them in the website and the operator reads the log by command.
The client chooses one of the two.

## Acknowledgment

MC Labor Sources Inc. has read the arrangement and the six risks above and accepts them as the security arrangement for
the production search website, with the actions in the last column as the company's responsibility.

Name and role: ______________________________   Date: ______________   Signature: ______________________________

Shared identity in `WEB_ADMINS` (sees the administrator pages):  [ ] yes   [ ] no

Staff record everyone acts as (`SITE_DEFAULT_USER`, initials): __________
