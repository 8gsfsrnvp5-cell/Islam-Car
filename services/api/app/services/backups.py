"""Резервное копирование базы и файлов и проверка восстановления.

Копии создаются утилитой pg_dump (формат custom) и архивом каталога файлов.
Проверка: целостность архива (pg_restore --list), совпадение контрольной суммы и, если задана
отдельная база BACKUP_VERIFY_DATABASE_URL, полное восстановление в неё с подсчётом договоров.
"""

import hashlib
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BackupRun

DUMP_PREFIX = "islamcar-db-"
FILES_PREFIX = "islamcar-files-"


def libpq_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _finish(run: BackupRun, status: str, detail: str = "") -> BackupRun:
    run.status = status
    run.detail = detail
    run.finished_at = datetime.now(UTC)
    return run


def run_backup(db: Session, now: datetime) -> BackupRun:
    s = get_settings()
    run = BackupRun(kind="backup", status="running", started_at=now)
    db.add(run)
    db.flush()
    if not s.database_url.startswith("postgresql"):
        return _finish(run, "skipped", "Резервное копирование выполняется только для PostgreSQL")
    if not s.backup_dir:
        return _finish(run, "skipped", "Каталог BACKUP_DIR не задан")
    target = Path(s.backup_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    dump = target / f"{DUMP_PREFIX}{stamp}.dump"
    try:
        proc = subprocess.run([s.pg_dump_path, "-Fc", "--no-owner", "-f", str(dump), "--dbname",
                               libpq_url(s.database_url)], capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return _finish(run, "failed", f"pg_dump не запустился: {e}")
    if proc.returncode != 0:
        dump.unlink(missing_ok=True)
        return _finish(run, "failed", f"pg_dump: {proc.stderr.strip()[:2000]}")

    files_note = ""
    storage = Path(s.storage_dir)
    if storage.is_dir():
        archive = target / f"{FILES_PREFIX}{stamp}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for f in storage.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(storage))
        run.files_name, run.files_sha256 = archive.name, sha256_file(archive)
        files_note = f"; файлы: {archive.name}"

    run.file_name = dump.name
    run.size_bytes = dump.stat().st_size
    run.sha256 = sha256_file(dump)
    removed = cleanup(target, now, s.backup_retention_days)
    return _finish(run, "ok", f"Копия базы создана{files_note}; удалено устаревших файлов: {removed}")


def cleanup(target: Path, now: datetime, retention_days: int) -> int:
    cutoff = (now - timedelta(days=retention_days)).timestamp()
    removed = 0
    for f in target.iterdir():
        if f.name.startswith((DUMP_PREFIX, FILES_PREFIX)) and f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed


def verify_latest(db: Session, now: datetime) -> BackupRun:
    s = get_settings()
    run = BackupRun(kind="verify", status="running", started_at=now)
    db.add(run)
    db.flush()
    latest = db.scalar(select(BackupRun).where(BackupRun.kind == "backup", BackupRun.status == "ok")
                       .order_by(BackupRun.started_at.desc()).limit(1))
    if not latest or not s.backup_dir:
        return _finish(run, "skipped", "Нет успешных резервных копий для проверки")
    path = Path(s.backup_dir) / latest.file_name
    run.file_name = latest.file_name
    if not path.is_file():
        return _finish(run, "failed", "Файл резервной копии не найден")
    if sha256_file(path) != latest.sha256:
        return _finish(run, "failed", "Контрольная сумма не совпадает — файл повреждён или изменён")
    try:
        listing = subprocess.run([s.pg_restore_path, "--list", str(path)], capture_output=True, text=True,
                                 timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return _finish(run, "failed", f"pg_restore не запустился: {e}")
    if listing.returncode != 0 or "TABLE DATA public contracts" not in listing.stdout:
        return _finish(run, "failed", f"Архив не читается: {listing.stderr.strip()[:1000]}")
    if latest.files_name:
        archive = Path(s.backup_dir) / latest.files_name
        if not archive.is_file() or sha256_file(archive) != latest.files_sha256:
            return _finish(run, "failed", "Архив файлов отсутствует или контрольная сумма не совпадает")
        try:
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None:
                    return _finish(run, "failed", "Архив файлов повреждён")
        except (OSError, zipfile.BadZipFile):
            return _finish(run, "failed", "Архив файлов не читается")
    if not s.backup_verify_database_url:
        return _finish(run, "ok", "Архив цел, контрольная сумма совпадает. Полное восстановление не настроено "
                                  "(BACKUP_VERIFY_DATABASE_URL).")
    # Fail closed: never run --clean against a production database, including URL aliases.
    source_name = make_url(s.database_url).database
    target_name = make_url(s.backup_verify_database_url).database
    if not target_name or target_name == source_name or not target_name.endswith("_restore_check"):
        return _finish(run, "failed", "Восстановление разрешено только в отдельную базу с суффиксом _restore_check")
    with psycopg.connect(libpq_url(s.database_url)) as source_conn, \
            psycopg.connect(libpq_url(s.backup_verify_database_url)) as target_conn:
        actual_source = source_conn.execute("select current_database()").fetchone()[0]
        actual_target = target_conn.execute("select current_database()").fetchone()[0]
        if actual_target == actual_source or actual_target != target_name:
            return _finish(run, "failed", "База проверки совпадает с исходной или скрыта подключением")
    restore = subprocess.run([s.pg_restore_path, "--clean", "--if-exists", "--no-owner", "--dbname",
                              libpq_url(s.backup_verify_database_url), str(path)],
                             capture_output=True, text=True, timeout=3600)
    if restore.returncode != 0:
        return _finish(run, "failed", f"Восстановление не удалось: {restore.stderr.strip()[:2000]}")
    with psycopg.connect(libpq_url(s.backup_verify_database_url)) as conn:
        contracts = conn.execute("select count(*) from contracts").fetchone()[0]
    return _finish(run, "ok", f"Полное восстановление выполнено в отдельную базу; договоров: {contracts}")
