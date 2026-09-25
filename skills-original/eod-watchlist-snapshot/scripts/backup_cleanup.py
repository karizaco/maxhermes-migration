"""TTL-based cleanup for research/ backup folders.

Keeps the most recent N backup directories; older ones get moved to
research/backup_archive/. Pattern matches:
  research/universe_cache_backup_YYYY-MM-DD/
  research/universe_cache_backup_pre_*_YYYY-MM-DD/
  research/historical_eod/YYYY-MM-DD.bak/

Usage:
  python backup_cleanup.py           # dry-run, prints what would move
  python backup_cleanup.py --apply   # actually moves to backup_archive/
  python backup_cleanup.py --keep 3  # keep this many backups (default 3)

Cron pattern (Sunday 03:00 UTC):
  mavis cron create --schedule "0 3 * * 0" --prompt "..."
"""
from __future__ import annotations
import argparse
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(r"C:\Users\admin\.minimax\projects\coding-shared\research")
ARCHIVE = ROOT / "backup_archive"

# Match: universe_cache_backup_YYYY-MM-DD, universe_cache_backup_pre_*_YYYY-MM-DD,
# or any *_YYYY-MM-DD.bak directory
BACKUP_PATTERN = re.compile(r".+_(\d{4}-\d{2}-\d{2})$|.+_(\d{4}-\d{2}-\d{2})\.bak$")


def date_from_name(name: str) -> date | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if not m:
        return None
    try:
        y, mo, d = m.group(1).split("-")
        return date(int(y), int(mo), int(d))
    except ValueError:
        return None


def find_backups() -> list[tuple[Path, date]]:
    """Return [(path, date), ...] for all backups in research/, sorted desc by date."""
    found: list[tuple[Path, date]] = []
    for p in ROOT.iterdir():
        if not p.is_dir():
            continue
        if BACKUP_PATTERN.match(p.name):
            d = date_from_name(p.name)
            if d:
                found.append((p, d))
        # Also scan historical_eod/ for .bak folders
        if p.name == "historical_eod":
            for sub in p.iterdir():
                if sub.is_dir() and sub.name.endswith(".bak"):
                    d = date_from_name(sub.name)
                    if d:
                        found.append((sub, d))
    found.sort(key=lambda x: x[1], reverse=True)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually move backups (default: dry-run)")
    parser.add_argument("--keep", type=int, default=3,
                        help="Number of most-recent backups to keep (default 3)")
    args = parser.parse_args()

    backups = find_backups()
    print(f"Found {len(backups)} backup directories:")
    for p, d in backups:
        marker = "*KEEP*" if backups.index((p, d)) < args.keep else "archive"
        print(f"  [{marker}] {d}  {p}")
    if len(backups) <= args.keep:
        print("\nNothing to archive.")
        return

    to_archive = backups[args.keep:]
    print(f"\nWill archive {len(to_archive)} backup(s) older than {args.keep} most-recent.")
    if not args.apply:
        print("(dry-run; pass --apply to actually move)")
        return

    ARCHIVE.mkdir(exist_ok=True)
    for p, d in to_archive:
        dest = ARCHIVE / p.name
        if dest.exists():
            print(f"  ! {dest.name} already in archive; skipping")
            continue
        shutil.move(str(p), str(dest))
        print(f"  moved {p.name} -> backup_archive/")
    print(f"\nDone. {len(to_archive)} backup(s) archived.")


if __name__ == "__main__":
    main()
