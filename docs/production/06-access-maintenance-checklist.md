# 6. Maintenance checklist: protecting people working in Access

> **Which database?** Names are defined in `docs/environments.md`. DEV-PC holds a **restored copy** (staging), not the live database. This document was first written believing DEV-PC was live. Use it as written for the copy; for the possible live database on LIVE-HOST see `09-plan-connect-live-database.md`.

On the restored copy (DEV-PC) only the two Access files on that PC's Desktop are affected, so this checklist is
needed in full only for the server office staff actually use (LIVE-HOST, if confirmed).

Use this for anything that restarts SQL Server: the update (several minutes) and the certificate (about a minute).
Creating the read-only login does **not** need it.

When SQL Server stops, every open Access screen loses its connection. A record someone is half-way through typing
is lost, and Access usually has to be closed and reopened.

## The day before

- [ ] Choose a time outside working hours, or when the office can stop for 30 minutes.
- [ ] Tell everyone who uses Access, by name: the date, the time, and "save your work and close Access completely
      before then; do not open it again until told".
- [ ] Decide who gives the all-clear afterwards.
- [ ] Backup made and restore-tested (`01-backup-and-restore-checklist.md`).

## 15 minutes before

- [ ] Remind everyone. Ask each person to finish the record they are on and close Access.
- [ ] Walk round, or call: every Access window is closed, including on PCs left on overnight.

## Immediately before: confirm nobody is connected (changes nothing)

In SSMS, as a SQL Server administrator: File > Open > `tools\prod-check\list-active-sessions.sql` > Execute.

- [ ] The list is empty, or shows only your own SSMS session.
- If someone is still listed: the `host_name` column is their PC and `login_name` is their sign-in. Ask them to
  close Access. Do not disconnect them from the server yourself; that loses their unsaved work.
- A session that shows an old `last_request_end_time` is probably an Access window left open with nobody at it.
  It still needs closing at that PC.

## During

- [ ] Do the one planned task only. Do not combine the update and the certificate in one sitting.
- [ ] Note the start and end time.

## Afterwards

- [ ] On this PC: open Access, look up a record, edit and save a harmless field, change it back.
- [ ] On one other PC: the same.
- [ ] Give the all-clear.
- [ ] If Access shows connection errors on a PC that was left open: close Access completely and open it again.

## If it goes wrong

- [ ] Do not let people start working until SQL Server is confirmed running (Services > `SQL Server (SQLEXPRESS)`
      shows "Running").
- [ ] Use the rollback in the plan you were following (`03` for the update, `04` for the certificate).
- [ ] Tell everyone what happened and when they can work again.
