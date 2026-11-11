"""Online SQLite backup, run by the fixed Ubuntu timer."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main():
    os.umask(0o077)
    source = Path("/var/lib/regional-vpn/control.db")
    target = Path("/var/backups/regional-vpn")
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("control-%Y%m%dT%H%M%S%fZ.db")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        with sqlite3.connect(target / name) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    print("Backup verified:", name)


if __name__ == "__main__":
    main()
