"""Backup del database SignalDesk (G1).

- SQLite: copia consistente a caldo tramite l'API ``Connection.backup``
  (sicura anche mentre l'applicazione è in esecuzione).
- PostgreSQL: invoca ``pg_dump`` in formato custom (richiede il client
  PostgreSQL nel PATH). Per il setup Docker di produzione esiste anche
  ``scripts/backup_postgres.sh``, che esegue il dump dentro il container.

Uso:

```powershell
python scripts/backup.py                 # backup in ./backups
python scripts/backup.py --dir D:\\safe  # directory destinazione
python scripts/backup.py --keep 30       # retention: ultimi 30 backup
```

La retention elimina i backup più vecchi oltre il numero indicato
(default 14), non i giorni: con backup orari si conservano ~14 esecuzioni.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _backup_dir(value: str | None) -> Path:
    path = Path(value) if value else ROOT / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _apply_retention(backup_dir: Path, pattern: str, keep: int) -> list[Path]:
    backups = sorted(backup_dir.glob(pattern), reverse=True)
    removed: list[Path] = []
    for old in backups[keep:]:
        old.unlink()
        removed.append(old)
    return removed


def backup_sqlite(database_url: str, backup_dir: Path) -> Path:
    db_path = Path(database_url.replace("sqlite:///", "", 1))
    if not db_path.exists():
        raise SystemExit(f"Database SQLite non trovato: {db_path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"signaldesk-{stamp}.db"
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def backup_postgres(database_url: str, backup_dir: Path) -> Path:
    if not shutil.which("pg_dump"):
        raise SystemExit(
            "pg_dump non trovato nel PATH. Installa il client PostgreSQL "
            "oppure usa scripts/backup_postgres.sh con il setup Docker."
        )
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"signaldesk-{stamp}.dump"
    with target.open("wb") as handle:
        subprocess.run(
            ["pg_dump", "--format=custom", "--dbname", dsn],
            stdout=handle, check=True,
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup del database SignalDesk")
    parser.add_argument("--dir", help="Directory di destinazione (default: ./backups)")
    parser.add_argument(
        "--keep", type=int, default=14,
        help="Numero di backup da conservare (default: 14)",
    )
    args = parser.parse_args()

    backup_dir = _backup_dir(args.dir)
    database_url = os.getenv(
        "DATABASE_URL", f"sqlite:///{(ROOT / 'social_intelligence.db').as_posix()}"
    )
    if database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        target = backup_postgres(database_url, backup_dir)
        removed = _apply_retention(backup_dir, "signaldesk-*.dump", max(args.keep, 1))
    elif database_url.startswith("sqlite:///"):
        target = backup_sqlite(database_url, backup_dir)
        removed = _apply_retention(backup_dir, "signaldesk-*.db", max(args.keep, 1))
    else:
        raise SystemExit(f"DATABASE_URL non supportata per il backup: {database_url}")

    print(f"Backup creato: {target}")
    for old in removed:
        print(f"Retention: eliminato {old.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
