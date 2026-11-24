"""Read-only inventory of the Access application's object names (forms, reports, queries, macros, modules).

Reads the .accdb/.mdb files on this PC's Desktop as bytes (never opened in Access, no table data read) and collects
names that follow the Access naming prefixes, in UTF-16LE and ASCII encodings. Prints a count per prefix and writes
the distinct names to a text file. No record data, no passwords: only object names.
"""
import mmap
import re
import sys
from collections import defaultdict
from pathlib import Path

PREFIXES = ("frm", "rpt", "qry", "mcr", "mod", "bas", "sfrm", "fsub", "subfrm", "srpt")
out_path = Path(sys.argv[1])
files = [Path(p) for p in sys.argv[2:]]

ascii_re = re.compile(rb"\b(?:frm|rpt|qry|mcr|mod|bas|sfrm|fsub|subfrm|srpt)[A-Za-z][A-Za-z0-9_]{2,60}")
utf16_re = re.compile(rb"(?:(?:f\x00r\x00m\x00)|(?:r\x00p\x00t\x00)|(?:q\x00r\x00y\x00)|(?:m\x00c\x00r\x00)|(?:s\x00f\x00r\x00m\x00)|(?:f\x00s\x00u\x00b\x00)|(?:s\x00r\x00p\x00t\x00))(?:[A-Za-z0-9_]\x00){3,60}")

names: dict[str, set[str]] = defaultdict(set)
per_file: dict[str, dict[str, int]] = {}
for f in files:
    found: dict[str, int] = defaultdict(int)
    with f.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for m in ascii_re.finditer(mm):
            s = m.group(0).decode("ascii", "ignore")
            if not s.isascii():
                continue
            names[f.name].add(s)
            found["ascii"] += 1
        for m in utf16_re.finditer(mm):
            raw = m.group(0)
            try:
                s = raw.decode("utf-16-le")
            except UnicodeDecodeError:
                continue
            names[f.name].add(s)
            found["utf16"] += 1
    per_file[f.name] = dict(found)

all_names = sorted(set().union(*names.values())) if names else []
with out_path.open("w", encoding="utf-8") as out:
    out.write(f"files: {', '.join(f.name for f in files)}\n")
    for f, counts in per_file.items():
        out.write(f"{f}: matches {counts}\n")
    out.write(f"distinct names: {len(all_names)}\n")
    for n in all_names:
        out.write(n + "\n")
by_prefix = defaultdict(int)
for n in all_names:
    for p in sorted(PREFIXES, key=len, reverse=True):
        if n.lower().startswith(p):
            by_prefix[p] += 1
            break
print("distinct names:", len(all_names))
print("by prefix:", dict(by_prefix))
print("written:", out_path)
