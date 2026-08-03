#!/usr/bin/env python3
"""One-time rename of snapshot files from naive local (Asia/Kuala_Lumpur) stamps
to ET stamps, so one US trading session lands in one date bucket.

Local midnight here is 12:00 ET, so the old naive-local filenames split every
session across two date buckets mid-day. The writers now stamp in ET; this
brings the existing history in line.

Only the filename changes - each file's contents are left alone. Consumers that
read the payload 'timestamp' already handle both naive-local (pre-switchover)
and tz-aware ET (post-switchover) values.

    python3 migrate_filenames_to_et.py            # dry run, prints a summary
    python3 migrate_filenames_to_et.py --apply    # actually rename
    python3 migrate_filenames_to_et.py --apply --revert   # undo (ET -> local)
"""

import argparse
import glob
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ET_TZ = ZoneInfo('America/New_York')
LOCAL_TZ = ZoneInfo('Asia/Kuala_Lumpur')

# (directory, glob pattern) pairs whose date part the dashboards bucket on.
TARGETS = [
    ('momentum_data', 'raw_data_*.json'),
    ('momentum_data', 'alerts_*.json'),
    ('pretop20', 'screener_*.json'),
    ('pretop20', 'notification_*.txt'),
]

STAMP_RE = re.compile(r'^(?P<prefix>.+_)(?P<date>\d{8})_(?P<time>\d{6})(?P<ext>\.[^.]+)$')


def converted_name(basename, src_tz, dst_tz):
    """Reinterpret the embedded stamp as src_tz and rewrite it in dst_tz."""
    m = STAMP_RE.match(basename)
    if not m:
        return None
    try:
        stamp = datetime.strptime(m['date'] + m['time'], '%Y%m%d%H%M%S')
    except ValueError:
        return None
    moved = stamp.replace(tzinfo=src_tz).astimezone(dst_tz)
    return f"{m['prefix']}{moved:%Y%m%d_%H%M%S}{m['ext']}"


def plan(revert):
    src_tz, dst_tz = (ET_TZ, LOCAL_TZ) if revert else (LOCAL_TZ, ET_TZ)
    renames, skipped = [], []
    for subdir, pattern in TARGETS:
        directory = os.path.join(BASE_DIR, subdir)
        for path in sorted(glob.glob(os.path.join(directory, pattern))):
            basename = os.path.basename(path)
            new_name = converted_name(basename, src_tz, dst_tz)
            if new_name is None:
                skipped.append(path)
                continue
            if new_name != basename:
                renames.append((path, os.path.join(directory, new_name)))
    return renames, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='perform the renames')
    ap.add_argument('--revert', action='store_true', help='ET -> local instead')
    args = ap.parse_args()

    renames, skipped = plan(args.revert)

    # A same-directory rename onto an existing path would destroy data. The
    # local<->ET offset is constant across this history, so collisions mean
    # something unexpected; refuse the whole batch rather than half-migrate.
    existing = {p for p, _ in renames}
    collisions = [(s, d) for s, d in renames if os.path.exists(d) and d not in existing]
    duplicates = len(renames) - len({d for _, d in renames})

    print(f"{'REVERT' if args.revert else 'MIGRATE'}: {len(renames)} file(s) to rename, "
          f"{len(skipped)} unparseable (left alone)")
    for src, dst in renames[:3] + (renames[-3:] if len(renames) > 6 else []):
        print(f"  {os.path.basename(src)} -> {os.path.basename(dst)}")
    if len(renames) > 6:
        print(f"  ... {len(renames) - 6} more")

    if collisions or duplicates:
        print(f"\nABORT: {len(collisions)} target(s) already exist, "
              f"{duplicates} duplicate target(s). Nothing renamed.")
        return 1

    if not args.apply:
        print("\nDry run. Re-run with --apply to rename.")
        return 0

    for src, dst in renames:
        os.rename(src, dst)
    print(f"\nRenamed {len(renames)} file(s).")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
