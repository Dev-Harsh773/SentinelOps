"""Consistent SQLite backup and isolated restore: python -m app.backup --help.

Both operations refuse to overwrite any existing destination. Workspaces are
separate durable files and must also be copied while repository mutations stop.
"""
import argparse
import os
from pathlib import Path
import sqlite3


def copy_database(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    # Read-only URI prevents a typo from creating an empty source database.
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as reader:
        if reader.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Source database failed integrity validation")
        if not reader.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
            raise ValueError("Source database has no application tables")
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with sqlite3.connect(destination) as writer:
                reader.backup(writer)
                if writer.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("Destination database failed integrity validation")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, help="New file in an existing directory")
    args = parser.parse_args()
    copy_database(args.source, args.destination)
    print(f"{args.operation.capitalize()} completed; integrity check passed.")


if __name__ == "__main__":
    main()
