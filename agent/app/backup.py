"""Atomic, self-contained backups for the P1 SQLite Agent store.

The archive is deliberately a single file so its database and compatibility
metadata are published together. Database contents are copied with SQLite's
online backup API; copying an open database's main file would omit committed
WAL pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contracts import API_VERSION, EXECUTION_KEY_VERSION, OPERATIONS_VERSION, SEMANTIC_VERSION
from .store import SQLiteAgentStore


_ARCHIVE_FORMAT = "shared-ledger-agent-sqlite-backup"
_ARCHIVE_FORMAT_VERSION = 1
_DATABASE_ENTRY = "database.sqlite3"
_MANIFEST_ENTRY = "manifest.json"
_COPY_CHUNK_BYTES = 1024 * 1024
_BACKUP_PAGES = 128
_BACKUP_SLEEP_SECONDS = 0.025
_MAX_TIMEOUT_SECONDS = 3600.0


class BackupError(RuntimeError):
    """Sanitized backup/restore failure safe for command-line diagnostics."""

    exit_code = 6


class BackupSourceError(BackupError):
    """The requested source database is absent or cannot be opened."""

    exit_code = 3


class BackupTargetError(BackupError):
    """Restore destination preconditions are not met."""

    exit_code = 3


class BackupValidationError(BackupError):
    """A backup/database is malformed, corrupt, or incompatible with this build."""

    exit_code = 4


class BackupTimeout(BackupError):
    """A backup, verification, or restore exceeded its finite deadline."""

    exit_code = 5


@dataclass(frozen=True)
class BackupInfo:
    """Public details for one verified backup artifact."""

    path: Path
    archive_sha256: str
    database_sha256: str
    size_bytes: int
    schema_version: int


@dataclass(frozen=True)
class RestoreInfo:
    """Public details for a successfully published restored database."""

    path: Path
    database_sha256: str
    size_bytes: int
    schema_version: int


class _Deadline:
    def __init__(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (float, int)):
            raise ValueError("timeout_seconds must be a finite positive number")
        timeout = float(seconds)
        if not math.isfinite(timeout) or timeout <= 0 or timeout > _MAX_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be a finite positive number no greater than one hour")
        self._expires_at = time.monotonic() + timeout

    @property
    def remaining(self) -> float:
        return max(0.0, self._expires_at - time.monotonic())

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._expires_at

    def check(self) -> None:
        if self.expired:
            raise BackupTimeout("operation exceeded its time limit")

    @property
    def sqlite_timeout(self) -> float:
        return min(0.1, self.remaining)


def create_backup(
    source_path: str | os.PathLike[str],
    backup_path: str | os.PathLike[str],
    *,
    timeout_seconds: float = 10.0,
) -> BackupInfo:
    """Create and atomically publish a single-file live SQLite snapshot."""

    deadline = _Deadline(timeout_seconds)
    source = Path(source_path)
    destination = Path(backup_path)
    source = _existing_file(source, source_error=True)
    _validate_parent(destination, source_error=False)
    try:
        if destination.exists() and os.path.samefile(source, destination):
            raise BackupTargetError("backup destination must differ from its source database")
    except OSError:
        pass

    staged_db: Path | None = None
    staged_archive: Path | None = None
    try:
        staged_db = _temporary_path(destination.parent, ".shared-ledger-db-")
        _snapshot_source(source, staged_db, deadline)
        _normalize_and_validate_database(staged_db, deadline)
        database_hash, database_size = _hash_file(staged_db, deadline)
        schema_version, migrations = _database_compatibility(staged_db, deadline)
        manifest = _make_manifest(database_hash, database_size, schema_version, migrations)

        staged_archive = _temporary_path(destination.parent, ".shared-ledger-backup-")
        _write_archive(staged_archive, staged_db, manifest, deadline)
        archive_hash, archive_size = _hash_file(staged_archive, deadline)
        _sync_file(staged_archive)
        deadline.check()
        os.replace(staged_archive, destination)
        staged_archive = None
        _sync_directory(destination.parent)
        return BackupInfo(destination, archive_hash, database_hash, archive_size, schema_version)
    except BackupError:
        raise
    except (sqlite3.Error, OSError, ValueError, zipfile.BadZipFile) as exc:
        if deadline.expired:
            raise BackupTimeout("operation exceeded its time limit") from None
        if _is_busy_error(exc):
            raise BackupTimeout("database remained busy until the operation time limit") from None
        if not source.exists():
            raise BackupSourceError("database source is unavailable") from None
        raise BackupError("backup could not be completed") from None
    finally:
        _remove_temp(staged_archive)
        _remove_temp(staged_db)


def verify_backup(
    backup_path: str | os.PathLike[str],
    *,
    timeout_seconds: float = 10.0,
) -> BackupInfo:
    """Verify the single-file archive, installed compatibility, and all DB rows."""

    deadline = _Deadline(timeout_seconds)
    archive_path = Path(backup_path)
    archive_path = _existing_file(archive_path, source_error=False)
    try:
        with tempfile.TemporaryDirectory(prefix="shared-ledger-verify-") as staging_directory:
            staged_db = Path(staging_directory) / _DATABASE_ENTRY
            database_hash, database_size, schema_version = _extract_and_validate(
                archive_path, staged_db, deadline,
            )
            archive_hash, archive_size = _hash_file(archive_path, deadline)
            return BackupInfo(archive_path, archive_hash, database_hash, archive_size, schema_version)
    except BackupError:
        raise
    except (sqlite3.Error, OSError, ValueError, zipfile.BadZipFile, KeyError, TypeError) as exc:
        if deadline.expired:
            raise BackupTimeout("operation exceeded its time limit") from None
        if _is_busy_error(exc):
            raise BackupTimeout("database remained busy until the operation time limit") from None
        raise BackupValidationError("backup is corrupt or incompatible with this build") from None


def restore_backup(
    backup_path: str | os.PathLike[str],
    target_path: str | os.PathLike[str],
    *,
    timeout_seconds: float = 10.0,
) -> RestoreInfo:
    """Restore a verified backup into a fresh database path without overwriting."""

    deadline = _Deadline(timeout_seconds)
    archive_path = Path(backup_path)
    archive_path = _existing_file(archive_path, source_error=False)
    target = Path(target_path)
    _validate_restore_target_before_work(target)
    staged_db: Path | None = None
    try:
        staged_db = _temporary_path(target.parent, ".shared-ledger-restore-")
        database_hash, database_size, schema_version = _extract_and_validate(
            archive_path, staged_db, deadline,
        )
        deadline.check()
        _validate_restore_target_before_work(target)
        _sync_file(staged_db)
        _publish_no_replace(staged_db, target)
        staged_db = None
        _sync_directory(target.parent)
        return RestoreInfo(target, database_hash, database_size, schema_version)
    except BackupError:
        raise
    except (sqlite3.Error, OSError, ValueError, zipfile.BadZipFile, KeyError, TypeError) as exc:
        if deadline.expired:
            raise BackupTimeout("operation exceeded its time limit") from None
        if _is_busy_error(exc):
            raise BackupTimeout("database remained busy until the operation time limit") from None
        if _target_or_sidecar_exists(target):
            raise BackupTargetError("restore requires an absent target database and sidecars") from None
        raise BackupError("restore could not be completed") from None
    finally:
        _remove_temp(staged_db)


def _snapshot_source(source: Path, staged_db: Path, deadline: _Deadline) -> None:
    """Use URI mode=rw so opening the source cannot create a missing database."""

    if not source.is_file():
        raise BackupSourceError("database source is unavailable")
    source_uri = source.resolve(strict=True).as_uri() + "?mode=rw"
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(
            source_uri, uri=True, timeout=deadline.sqlite_timeout, isolation_level=None,
        )
        destination_connection = sqlite3.connect(
            staged_db, timeout=deadline.sqlite_timeout, isolation_level=None,
        )

        def progress(_status: int, _remaining: int, _total: int) -> None:
            deadline.check()

        source_connection.backup(
            destination_connection,
            pages=_BACKUP_PAGES,
            progress=progress,
            sleep=min(_BACKUP_SLEEP_SECONDS, deadline.remaining),
        )
        deadline.check()
        _set_delete_journal(destination_connection)
    except BackupError:
        raise
    except sqlite3.Error as exc:
        if deadline.expired or _is_busy_error(exc):
            raise BackupTimeout("database remained busy until the operation time limit") from None
        raise BackupSourceError("database source could not be read") from None
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()


def _normalize_and_validate_database(database_path: Path, deadline: _Deadline) -> None:
    if not database_path.is_file():
        raise BackupValidationError("database snapshot is missing")
    _set_delete_journal_path(database_path, deadline)
    _assert_no_sidecars(database_path)
    _validate_database(database_path, deadline)
    deadline.check()


def _validate_database(database_path: Path, deadline: _Deadline) -> None:
    """Run the same installed migration, integrity, FK, and typed-row checks as startup."""

    if not database_path.is_file():
        raise BackupValidationError("database snapshot is missing")
    store = SQLiteAgentStore(database_path, busy_timeout_seconds=max(0.001, deadline.sqlite_timeout))
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            database_path.resolve(strict=True).as_uri() + "?mode=ro",
            uri=True,
            timeout=deadline.sqlite_timeout,
            isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout={max(1, int(deadline.sqlite_timeout * 1000))}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.row_factory = sqlite3.Row
        connection.set_progress_handler(lambda: int(deadline.expired), 1000)
        connection.execute("BEGIN")
        mode_row = connection.execute("PRAGMA journal_mode").fetchone()
        if mode_row is None or str(mode_row[0]).lower() != "delete":
            raise BackupValidationError("database must be a self-contained rollback-journal file")
        store._verify_schema(connection)
        deadline.check()
        store._verify_database_integrity(connection)
        deadline.check()
        store._verify_all_rows(connection)
        deadline.check()
        connection.execute("COMMIT")
    except BackupError:
        if connection is not None and connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    except Exception as exc:
        if connection is not None and connection.in_transaction:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if deadline.expired or _is_busy_error(exc) or "interrupted" in str(exc).lower():
            raise BackupTimeout("database validation exceeded its time limit") from None
        raise BackupValidationError("database is corrupt or incompatible with this build") from None
    finally:
        if connection is not None:
            connection.close()


def _extract_and_validate(
    archive_path: Path,
    staged_db: Path,
    deadline: _Deadline,
) -> tuple[str, int, int]:
    if not archive_path.is_file():
        raise BackupValidationError("backup is unavailable")
    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            entries = archive.infolist()
            if len(entries) != 2 or {entry.filename for entry in entries} != {_MANIFEST_ENTRY, _DATABASE_ENTRY}:
                raise BackupValidationError("backup archive entries are invalid")
            if any(entry.is_dir() or entry.file_size < 0 for entry in entries):
                raise BackupValidationError("backup archive entries are invalid")
            manifest_entry = archive.getinfo(_MANIFEST_ENTRY)
            if manifest_entry.file_size > 64 * 1024:
                raise BackupValidationError("backup manifest is invalid")
            manifest_bytes = _read_manifest(archive, manifest_entry, deadline)
            manifest = _parse_manifest(manifest_bytes)
            database_entry = archive.getinfo(_DATABASE_ENTRY)
            if database_entry.file_size != manifest["database_size_bytes"]:
                raise BackupValidationError("backup database size does not match its manifest")
            actual_hash, actual_size = _extract_database(archive, database_entry, staged_db, deadline)
            if actual_hash != manifest["database_sha256"] or actual_size != manifest["database_size_bytes"]:
                raise BackupValidationError("backup database digest does not match its manifest")
            _assert_compatible_manifest(manifest)
    except BackupError:
        raise
    except (zipfile.BadZipFile, RuntimeError, EOFError, OSError, KeyError, ValueError, TypeError) as exc:
        if deadline.expired:
            raise BackupTimeout("operation exceeded its time limit") from None
        raise BackupValidationError("backup is corrupt or incompatible with this build") from None

    _assert_no_sidecars(staged_db)
    _validate_database(staged_db, deadline)
    schema_version, installed_migrations = _database_compatibility(staged_db, deadline)
    if manifest["schema_version"] != schema_version or manifest["migrations"] != installed_migrations:
        raise BackupValidationError("backup schema metadata does not match its database")
    return actual_hash, actual_size, schema_version


def _read_manifest(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    deadline: _Deadline,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    try:
        with archive.open(entry, mode="r") as source:
            while True:
                deadline.check()
                chunk = source.read(min(8192, 64 * 1024 + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > 64 * 1024:
                    raise BackupValidationError("backup manifest is invalid")
                chunks.append(chunk)
    except BackupError:
        raise
    return b"".join(chunks)


def _extract_database(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    destination: Path,
    deadline: _Deadline,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with archive.open(entry, mode="r") as source, destination.open("wb") as target:
            while True:
                deadline.check()
                chunk = source.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except BackupError:
        raise
    return digest.hexdigest(), size


def _write_archive(
    archive_path: Path,
    database_path: Path,
    manifest: dict[str, object],
    deadline: _Deadline,
) -> None:
    encoded_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.writestr(_MANIFEST_ENTRY, encoded_manifest)
            with database_path.open("rb") as source, archive.open(_DATABASE_ENTRY, mode="w") as target:
                while True:
                    deadline.check()
                    chunk = source.read(_COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    target.write(chunk)
    except BackupError:
        raise


def _make_manifest(
    database_hash: str,
    database_size: int,
    schema_version: int,
    migrations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "archive_format": _ARCHIVE_FORMAT,
        "archive_format_version": _ARCHIVE_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_entry": _DATABASE_ENTRY,
        "database_sha256": database_hash,
        "database_size_bytes": database_size,
        "execution_key_version": EXECUTION_KEY_VERSION,
        "migrations": migrations,
        "operations_version": OPERATIONS_VERSION,
        "api_version": API_VERSION,
        "schema_version": schema_version,
        "semantic_version": SEMANTIC_VERSION,
    }


def _parse_manifest(encoded: bytes) -> dict[str, object]:
    try:
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise BackupValidationError("backup manifest is invalid") from None
    expected_keys = {
        "archive_format", "archive_format_version", "created_at", "database_entry",
        "database_sha256", "database_size_bytes", "execution_key_version", "migrations",
        "operations_version", "api_version", "schema_version", "semantic_version",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise BackupValidationError("backup manifest is invalid")
    if (
        value["archive_format"] != _ARCHIVE_FORMAT
        or type(value["archive_format_version"]) is not int
        or value["archive_format_version"] != _ARCHIVE_FORMAT_VERSION
    ):
        raise BackupValidationError("backup format is unsupported")
    if value["database_entry"] != _DATABASE_ENTRY:
        raise BackupValidationError("backup manifest is invalid")
    digest = value["database_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise BackupValidationError("backup manifest is invalid")
    if type(value["database_size_bytes"]) is not int or value["database_size_bytes"] < 0:
        raise BackupValidationError("backup manifest is invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] < 1:
        raise BackupValidationError("backup manifest is invalid")
    if not isinstance(value["migrations"], list):
        raise BackupValidationError("backup manifest is invalid")
    for migration in value["migrations"]:
        if (
            not isinstance(migration, dict)
            or set(migration) != {"version", "name", "sha256"}
            or type(migration["version"]) is not int
            or migration["version"] < 1
            or not isinstance(migration["name"], str)
            or not isinstance(migration["sha256"], str)
            or len(migration["sha256"]) != 64
            or any(ch not in "0123456789abcdef" for ch in migration["sha256"])
        ):
            raise BackupValidationError("backup manifest is invalid")
    created_at = value["created_at"]
    if not isinstance(created_at, str):
        raise BackupValidationError("backup manifest is invalid")
    try:
        parsed_time = datetime.fromisoformat(created_at)
    except ValueError:
        raise BackupValidationError("backup manifest is invalid") from None
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise BackupValidationError("backup manifest is invalid")
    for key in ("api_version", "semantic_version", "operations_version", "execution_key_version"):
        if not isinstance(value[key], str):
            raise BackupValidationError("backup manifest is invalid")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _assert_compatible_manifest(manifest: dict[str, object]) -> None:
    if (
        manifest["api_version"] != API_VERSION
        or manifest["semantic_version"] != SEMANTIC_VERSION
        or manifest["operations_version"] != OPERATIONS_VERSION
        or manifest["execution_key_version"] != EXECUTION_KEY_VERSION
    ):
        raise BackupValidationError("backup protocol versions are incompatible with this build")
    installed = _installed_migrations()
    if manifest["migrations"] != installed:
        raise BackupValidationError("backup migration checksums are incompatible with this build")


def _database_compatibility(database_path: Path, deadline: _Deadline) -> tuple[int, list[dict[str, object]]]:
    deadline.check()
    store = SQLiteAgentStore(database_path, busy_timeout_seconds=max(0.001, deadline.sqlite_timeout))
    try:
        migrations = _installed_migrations_from_store(store)
        connection = sqlite3.connect(
            database_path.resolve(strict=True).as_uri() + "?mode=ro",
            uri=True,
            timeout=deadline.sqlite_timeout,
            isolation_level=None,
        )
        try:
            connection.set_progress_handler(lambda: int(deadline.expired), 1000)
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            records = [
                {"version": int(row[0]), "name": str(row[1]), "sha256": str(row[2])}
                for row in connection.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version")
            ]
            deadline.check()
            if records != migrations or version != (migrations[-1]["version"] if migrations else 0):
                raise BackupValidationError("database migration metadata does not match installed code")
            return version, records
        finally:
            connection.close()
    except BackupError:
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        if deadline.expired or _is_busy_error(exc) or "interrupted" in str(exc).lower():
            raise BackupTimeout("database metadata validation exceeded its time limit") from None
        raise BackupValidationError("database migration metadata is invalid") from None


def _installed_migrations() -> list[dict[str, object]]:
    return _installed_migrations_from_store(SQLiteAgentStore(Path(".")))


def _installed_migrations_from_store(store: SQLiteAgentStore) -> list[dict[str, object]]:
    return [
        {"version": migration.version, "name": migration.name, "sha256": migration.checksum}
        for migration in store._migrations
    ]


def _set_delete_journal_path(database_path: Path, deadline: _Deadline) -> None:
    if not database_path.is_file():
        raise BackupValidationError("staged database is missing")
    uri = database_path.resolve(strict=True).as_uri() + "?mode=rw"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=deadline.sqlite_timeout, isolation_level=None)
        _set_delete_journal(connection)
    except BackupError:
        raise
    except sqlite3.Error as exc:
        if deadline.expired or _is_busy_error(exc):
            raise BackupTimeout("staged database remained busy") from None
        raise BackupValidationError("staged database could not be finalized") from None
    finally:
        if connection is not None:
            connection.close()


def _set_delete_journal(connection: sqlite3.Connection) -> None:
    mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
    if mode != "delete":
        raise BackupValidationError("staged database could not be made self-contained")


def _assert_no_sidecars(database_path: Path) -> None:
    if any(path.exists() for path in _sidecars(database_path)):
        raise BackupValidationError("staged database still depends on SQLite sidecar files")


def _sidecars(database_path: Path) -> tuple[Path, ...]:
    return tuple(Path(str(database_path) + suffix) for suffix in ("-wal", "-shm", "-journal"))


def _validate_restore_target_before_work(target: Path) -> None:
    if not target.parent.exists() or not target.parent.is_dir():
        raise BackupTargetError("restore target parent directory must already exist")
    if _target_or_sidecar_exists(target):
        raise BackupTargetError("restore requires an absent target database and sidecars")


def _target_or_sidecar_exists(target: Path) -> bool:
    if os.path.lexists(target):
        return True
    return any(os.path.lexists(sidecar) for sidecar in _sidecars(target))


def _publish_no_replace(staged_db: Path, target: Path) -> None:
    if _target_or_sidecar_exists(target):
        raise BackupTargetError("restore requires an absent target database and sidecars")
    if os.name == "nt":
        # Windows rename fails if the destination appeared after the preflight.
        os.rename(staged_db, target)
    else:
        # A hard link is atomic and, unlike POSIX rename, cannot replace a race winner.
        os.link(staged_db, target)
        staged_db.unlink()


def _existing_file(path: Path, *, source_error: bool) -> Path:
    try:
        if not path.is_file():
            raise OSError("not a regular file")
        return path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        if source_error:
            raise BackupSourceError("database source is unavailable") from None
        raise BackupValidationError("backup file is unavailable") from None


def _validate_parent(path: Path, *, source_error: bool) -> None:
    if not path.parent.exists() or not path.parent.is_dir():
        error = BackupSourceError if source_error else BackupError
        raise error("destination parent directory must already exist")


def _temporary_path(parent: Path, prefix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=parent)
    os.close(descriptor)
    return Path(name)


def _hash_file(path: Path, deadline: _Deadline) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while True:
            deadline.check()
            chunk = source.read(_COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _sync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _remove_temp(path: Path | None) -> None:
    if path is None:
        return
    for candidate in (path, *_sidecars(path)):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def _is_busy_error(error: BaseException) -> bool:
    text = str(error).lower()
    return "locked" in text or "busy" in text


def _positive_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a positive number of seconds") from None
    if not math.isfinite(parsed) or parsed <= 0 or parsed > _MAX_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError("timeout must be > 0 and at most 3600 seconds")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent.app.backup",
        description="Create, verify, or restore a self-contained P1 SQLite backup.",
        epilog=(
            "Exit codes: 0 success; 2 usage; 3 source/target precondition; "
            "4 corrupt or incompatible backup; 5 timeout/locked database; 6 operational failure."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="make an online backup of a running Agent database")
    backup.add_argument("--source", required=True, help="existing SQLite Agent database")
    backup.add_argument("--output", required=True, help="single-file backup archive path")
    backup.add_argument("--timeout-seconds", type=_positive_timeout, default=10.0)
    verify = commands.add_parser("verify", help="verify archive hash, compatibility, and stored rows")
    verify.add_argument("--backup", required=True, help="backup archive path")
    verify.add_argument("--timeout-seconds", type=_positive_timeout, default=10.0)
    restore = commands.add_parser("restore", help="restore to an absent database path")
    restore.add_argument("--backup", required=True, help="backup archive path")
    restore.add_argument("--target", required=True, help="new SQLite database path")
    restore.add_argument("--timeout-seconds", type=_positive_timeout, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            info = create_backup(args.source, args.output, timeout_seconds=args.timeout_seconds)
            print(f"backup created; sha256={info.archive_sha256}; size_bytes={info.size_bytes}")
        elif args.command == "verify":
            info = verify_backup(args.backup, timeout_seconds=args.timeout_seconds)
            print(f"backup verified; sha256={info.archive_sha256}; schema_version={info.schema_version}")
        else:
            info = restore_backup(args.backup, args.target, timeout_seconds=args.timeout_seconds)
            print(f"database restored; database_sha256={info.database_sha256}; schema_version={info.schema_version}")
        return 0
    except BackupError as exc:
        print(f"{exc}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError) as exc:
        # Do not print OS/SQLite messages: they may embed absolute paths or row data.
        print("operation could not be completed", file=sys.stderr)
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
