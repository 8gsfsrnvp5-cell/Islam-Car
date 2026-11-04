"""Версия 2: залоги, страхование, задачи и контроль сроков, резервные копии."""

import os
import re
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import StaffTask, TaskStatus
from app.services import backups, staff_tasks
from app.services.common import today
from tests.helpers import confirm_payment, signed_deal


def scan(now: datetime | None = None) -> int:
    with SessionLocal() as db:
        n = staff_tasks.scan(db, now or datetime.now(UTC))
        db.commit()
        return n


def open_tasks(kind: str) -> list[StaffTask]:
    with SessionLocal() as db:
        return list(db.scalars(select(StaffTask).where(StaffTask.kind == kind, StaffTask.status == TaskStatus.open)))


def test_pledge_lifecycle_follows_real_steps(admin):
    _, _, contract = signed_deal(admin)
    url = f"/api/admin/contracts/{contract['id']}/pledge"
    assert admin.get(url).json()["status"] == "planned"  # создаётся при подписании договора

    assert admin.put(url, json={"status": "registered"}).status_code == 409  # нельзя перескочить шаги
    assert admin.put(url, json={"status": "submitted", "notary": "Нотариус Т. Т."}).status_code == 200
    r = admin.put(url, json={"status": "registered"})
    assert r.status_code == 422  # без номера уведомления и даты — нельзя
    r = admin.put(url, json={"status": "registered", "registry_number": "2026-000-111111-222",
                             "registered_on": today().isoformat()})
    assert r.status_code == 200 and r.json()["allowed_next"] == ["release_required"]
    assert admin.put(url, json={"status": "release_required",
                                "registry_number": "2026-000-111111-222"}).status_code == 409  # долг не погашен

    confirm_payment(admin, contract["id"], 1_600_000)
    assert admin.get(url).json()["status"] == "release_required"  # автоматически после полной оплаты
    scan()
    assert open_tasks("pledge_release")
    r = admin.put(url, json={"status": "release_submitted", "registry_number": "2026-000-111111-222"})
    assert r.status_code == 200
    assert admin.put(url, json={"status": "released"}).status_code == 422
    r = admin.put(url, json={"status": "released", "release_number": "2026-000-333",
                             "released_on": today().isoformat()})
    assert r.json()["status"] == "released"


def test_overdue_tasks_created_once(admin):
    signed_deal(admin, contract_date=today() - timedelta(days=70))
    assert scan() >= 2
    assert len(open_tasks("overdue_contact")) == 1 and len(open_tasks("overdue_escalation")) == 1
    scan()
    assert len(open_tasks("overdue_contact")) == 1  # без дублей
    task = admin.get("/api/admin/tasks").json()[0]
    assert admin.post(f"/api/admin/tasks/{task['id']}/done", json={"note": "Позвонили, оплатит в пятницу"}).json()[
        "status"] == "done"
    assert admin.get("/api/admin/dashboard").json()["operations"]["open_tasks"] >= 1


def test_insurance_expiry_creates_task(admin):
    car, _, contract = signed_deal(admin)
    r = admin.post("/api/admin/insurance", json={
        "car_id": car["id"], "contract_id": contract["id"], "kind": "osago", "number": "XXX 0000000000",
        "insurer": "Тестовая страховая", "valid_from": (today() - timedelta(days=355)).isoformat(),
        "valid_to": (today() + timedelta(days=10)).isoformat(), "required_by_contract": True})
    assert r.status_code == 201
    scan()
    assert open_tasks("insurance")
    assert any("истекает" in n["title"] for n in admin.get("/api/admin/notifications").json())


def test_manual_task_and_worker_status(admin):
    r = admin.post("/api/admin/tasks", json={"title": "Проверить документы по Camry", "due_date": today().isoformat()})
    assert r.status_code == 201 and r.json()["automatic"] is False
    status = admin.get("/api/admin/worker").json()
    assert set(status["jobs"]) == {"queued", "running", "done", "failed", "cancelled"}


def test_backup_is_skipped_without_postgres_or_directory():
    with SessionLocal() as db:
        run = backups.run_backup(db, datetime.now(UTC))
        assert run.status == "skipped"


def _pg_dump_matches_server() -> bool:
    if engine.dialect.name != "postgresql" or os.environ.get("SKIP_BACKUP_TESTS"):
        return False
    try:
        out = subprocess.run([get_settings().pg_dump_path, "--version"], capture_output=True, text=True).stdout
    except OSError:
        return False
    with engine.connect() as conn:
        server = conn.exec_driver_sql("show server_version").scalar()
    client_major = re.search(r"(\d+)", out)
    return bool(client_major) and int(client_major.group(1)) >= int(server.split(".")[0])


@pytest.mark.skipif(not _pg_dump_matches_server(), reason="Нужны PostgreSQL и pg_dump той же или новее версии")
def test_backup_and_restore_check_on_postgres(admin, tmp_path, monkeypatch):
    signed_deal(admin)
    monkeypatch.setattr(get_settings(), "backup_dir", tmp_path)
    with SessionLocal() as db:
        run = backups.run_backup(db, datetime.now(UTC))
        db.commit()
        assert run.status == "ok", run.detail
        assert (tmp_path / run.file_name).stat().st_size > 0 and len(run.sha256) == 64
        check = backups.verify_latest(db, datetime.now(UTC))
        db.commit()
        assert check.status == "ok", check.detail
    runs = admin.get("/api/admin/backups").json()["runs"]
    assert {r["kind"] for r in runs} == {"backup", "verify"}
