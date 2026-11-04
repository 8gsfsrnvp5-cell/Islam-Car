"""Regression coverage for the November security audit."""
import io
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pyotp
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfWriter

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.main import app
from app.models import BackupRun, Role
from app.services import backups, online_payments
from app.services.uploads import validate_scan
from tests.conftest import OWNER_LOGIN, OWNER_PASSWORD, staff_client
from tests.helpers import (
    COMPANY,
    buyer_session,
    confirm_payment,
    create_car,
    create_contract,
    create_verified_client,
    setup_company,
    signed_deal,
    valid_png,
)


def owner_session():
    client = TestClient(app)
    assert client.post('/api/auth/admin/login', json={
        'login': OWNER_LOGIN, 'password': OWNER_PASSWORD}).status_code == 200
    return client


def test_password_change_revokes_other_sessions(admin):
    old = owner_session()
    assert admin.post('/api/auth/admin/password', json={
        'current_password': OWNER_PASSWORD, 'new_password': 'replacement-password-2'}).status_code == 200
    assert old.get('/api/auth/admin/me').status_code == 401
    assert admin.get('/api/auth/admin/me').status_code == 200
    assert TestClient(app).post('/api/auth/admin/login', json={
        'login': OWNER_LOGIN, 'password': OWNER_PASSWORD}).status_code == 401


def test_totp_enrollment_revokes_sessions_and_replay(admin):
    old = owner_session()
    secret = admin.post('/api/auth/admin/totp/setup').json()['secret']
    code = pyotp.TOTP(secret).now()
    assert admin.post('/api/auth/admin/totp/enable', json={'code': code}).status_code == 200
    assert old.get('/api/auth/admin/me').status_code == 401
    login = {'login': OWNER_LOGIN, 'password': OWNER_PASSWORD, 'totp_code': code}
    assert TestClient(app).post('/api/auth/admin/login', json=login).status_code == 401
    login['totp_code'] = pyotp.TOTP(secret).at(time.time() + 30)
    assert TestClient(app).post('/api/auth/admin/login', json=login).status_code == 200
    assert TestClient(app).post('/api/auth/admin/login', json=login).status_code == 401


def test_client_reactivation_revokes_existing_sessions(admin):
    _, client, _ = signed_deal(admin)
    old = buyer_session(admin, client['id'])
    buyer_session(admin, client['id'], password='changed-buyer-password')
    assert old.get('/api/auth/client/me').status_code == 401


def test_forwarded_header_does_not_bypass_ip_throttle(public):
    for n in range(20):
        assert public.post('/api/auth/admin/login', headers={'X-Forwarded-For': f'203.0.113.{n}'},
                           json={'login': f'user{n}', 'password': 'wrong'}).status_code == 401
    assert public.post('/api/auth/admin/login', headers={'X-Forwarded-For': '203.0.113.250'},
                       json={'login': 'different', 'password': 'wrong'}).status_code == 429


def test_draft_edit_replaces_schedule_without_duplicate_sequences(admin):
    setup_company(admin)
    car = create_car(admin)
    client = create_verified_client(admin)
    draft = create_contract(admin, client['id'], car['id'])
    path = f"/api/admin/contracts/{draft['id']}"
    for patch in ({'notes': 'Уточнены документы'}, {'term_months': 12}, {'down_payment_kopecks': 50_000_000}):
        response = admin.patch(path, json=patch)
        assert response.status_code == 200, response.text
        rows = response.json()['schedule']
        assert len({r['seq'] for r in rows}) == len(rows)
        assert sum(r['amount_kopecks'] for r in rows) == draft['sale_price_kopecks']
    assert len(admin.get(path).json()['schedule']) == 13


def test_restricted_roles_cannot_read_document_contents_or_client_login(admin):
    _, client, contract = signed_deal(admin)
    buyer_session(admin, client['id'])
    doc = admin.post('/api/admin/documents', json={
        'template_code': 'sale_contract', 'contract_id': contract['id']}).json()
    for role in (Role.accountant, Role.auditor, Role.manager, Role.lawyer, Role.shariah_advisor):
        staff = staff_client('test-' + role.value, role)
        for suffix in ('', '/export?format=docx', '/signed-file'):
            assert staff.get(f"/api/admin/documents/{doc['id']}{suffix}").status_code == 403
        assert staff.post('/api/admin/documents/preview', json={
            'template_code': 'sale_contract', 'contract_id': contract['id']}).status_code == 403
        if role in (Role.accountant, Role.auditor, Role.shariah_advisor):
            data = staff.get(f"/api/admin/clients/{client['id']}").json()
            assert data['cabinet_login'] is None and data['email'] == ''
            assert data['phone'] != client['phone']


def test_embedded_payments_follow_permissions(admin):
    _, _, contract = signed_deal(admin)
    confirm_payment(admin, contract['id'], 100)
    staff = staff_client('sharia-test', Role.shariah_advisor)
    data = staff.get(f"/api/admin/contracts/{contract['id']}").json()
    assert data['payments'] == [] and data['reports'] == []


def test_revoked_template_cannot_be_signed(admin):
    _, _, c = signed_deal(admin)
    admin.post('/api/admin/templates/payment_schedule/approve', json={'lawyer_name': 'Юрист Тестовый'})
    doc = admin.post('/api/admin/documents', json={
        'template_code': 'payment_schedule', 'contract_id': c['id']}).json()
    path = f"/api/admin/documents/{doc['id']}"
    assert admin.post(path + '/submit').status_code == 200
    assert admin.post(path + '/approve').status_code == 200
    assert admin.post('/api/admin/templates/payment_schedule/revoke').status_code == 200
    assert admin.post(path + '/signed', data={
        'signed_on': c['contract_date'], 'confirm_paper_signed': 'true'}).status_code == 409


def test_changed_sources_cannot_be_approved(admin):
    _, _, c = signed_deal(admin)
    doc = admin.post('/api/admin/documents', json={
        'template_code': 'payment_schedule', 'contract_id': c['id']}).json()
    path = f"/api/admin/documents/{doc['id']}"
    assert admin.post(path + '/submit').status_code == 200
    assert admin.put('/api/admin/settings', json={**COMPANY, 'seller_address': 'Новый адрес'}).status_code == 200
    assert admin.post(path + '/approve').status_code == 409


@pytest.mark.parametrize('change', [
    {'cookie_secure': False}, {'require_owner_2fa': False}, {'allowed_origins': '*'},
    {'client_public_url': 'http://client.example'}, {'payment_provider': 'sandbox'},
    {'yookassa_secret_key': 'test_secret'}, {'sms_provider': 'log'},
])
def test_production_rejects_unsafe_configuration(change):
    safe = dict(environment='production', cookie_secure=True, allowed_origins='https://admin.example',
                client_public_url='https://client.example', sms_provider='', email_provider='')
    Settings(_env_file=None, **safe)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(safe | change))


def test_test_payment_credentials_never_enabled_in_production(monkeypatch):
    s = get_settings()
    for key, value in dict(environment='production', payment_provider='yookassa', yookassa_shop_id='1',
                           yookassa_secret_key='test_secret', payment_receipts_confirmed=True).items():
        monkeypatch.setattr(s, key, value)
    assert online_payments.get_payment_provider() is None


def test_corrupt_or_active_scans_rejected():
    assert validate_scan(valid_png()) == ('image/png', '.png')
    for bad in (b'%PDF-1.7 garbage', b'\x89PNG\r\n\x1a\n' + b'\x00' * 64, b'\xff\xd8\xfffake'):
        with pytest.raises(HTTPException) as error:
            validate_scan(bad)
        assert error.value.status_code == 415
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    assert validate_scan(stream.getvalue()) == ('application/pdf', '.pdf')
    writer.add_js('app.alert("unsafe")')
    stream = io.BytesIO()
    writer.write(stream)
    with pytest.raises(HTTPException):
        validate_scan(stream.getvalue())


def test_backup_restore_never_targets_source_database(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, 'backup_dir', tmp_path)
    monkeypatch.setattr(s, 'database_url', 'postgresql+psycopg://user:password@db/live')
    monkeypatch.setattr(s, 'backup_verify_database_url', 'postgresql://other:password@alias/live')
    path = tmp_path / 'backup.dump'
    path.write_bytes(b'test-backup')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='TABLE DATA public contracts', stderr='')
    monkeypatch.setattr(backups.subprocess, 'run', run)
    with SessionLocal() as db:
        db.add(BackupRun(kind='backup', status='ok', started_at=datetime.now(UTC) - timedelta(hours=1),
                         file_name=path.name, sha256=backups.sha256_file(path)))
        db.commit()
        result = backups.verify_latest(db, datetime.now(UTC))
        assert result.status == 'failed'
    assert all('--clean' not in command for command in calls)


def test_large_request_rejected_before_parsing(public):
    response = public.post('/api/auth/admin/login', content=b'{}', headers={'Content-Length': str(25 * 1024 * 1024)})
    assert response.status_code == 413
    def chunks():
        for _ in range(25):
            yield b'x' * (1024 * 1024)
    assert public.post('/api/auth/admin/login', content=chunks()).status_code == 413


def test_assistant_requires_review_before_external_call(admin, monkeypatch):
    from app.services import assistant
    monkeypatch.setattr(get_settings(), 'anthropic_api_key', 'fake-key')
    admin.put('/api/admin/assistant/settings', json={'enabled': True, 'confirm_data_scope': True})
    def forbidden(*args, **kwargs):
        pytest.fail('Unreviewed question must never reach model')
    monkeypatch.setattr(assistant, 'call_model', forbidden)
    question = 'Можно ли продлить рассрочку?'
    assert admin.post('/api/admin/assistant/ask', json={'question': question}).status_code == 409
    assert admin.post('/api/admin/assistant/preview', json={'question': question}).json()['question'] == question
    assert admin.post('/api/admin/assistant/ask', json={
        'question': question, 'reviewed_question': 'different text'}).status_code == 409


def test_postgres_concurrent_payments_cannot_overpay(admin):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.db import engine
    from app.models import Contract, PaymentMethod
    from app.services.payments import record_payment
    if engine.dialect.name != 'postgresql':
        pytest.skip('Row locking requires PostgreSQL')
    _, _, contract = signed_deal(admin)
    gate = Barrier(2, timeout=10)
    def pay(n):
        with SessionLocal() as db:
            c = db.get(Contract, __import__('uuid').UUID(contract['id']))
            gate.wait()
            try:
                record_payment(db, c, amount_kopecks=100_000_000, received_on=c.contract_date,
                               method=PaymentMethod.bank_transfer, document_ref=f'concurrent-{n}', confirmed_by=None)
                db.commit()
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(pay, (1, 2))) == [201, 422]
    assert admin.get(f"/api/admin/contracts/{contract['id']}").json()['ledger']['paid_kopecks'] == 100_000_000


def test_postgres_live_worker_is_not_requeued_after_lease_expires():
    from sqlalchemy import text

    from app.db import engine
    from app.models import Job, JobStatus
    from app.worker.queue import requeue_stale
    if engine.dialect.name != 'postgresql':
        pytest.skip('Worker lock requires PostgreSQL')
    now = datetime.now(UTC)
    with SessionLocal() as db:
        job = Job(kind='backup', payload={}, run_at=now, status=JobStatus.running,
                  locked_until=now - timedelta(hours=1))
        db.add(job)
        db.commit()
        job_id = job.id
    with engine.connect() as active:
        params = {'key': str(job_id)}
        active.execute(text('SELECT pg_advisory_lock(hashtextextended(:key, 0))'), params)
        active.commit()
        try:
            with SessionLocal() as db:
                assert requeue_stale(db, now) == 0
                db.commit()
        finally:
            active.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key, 0))'), params)
            active.commit()
    with SessionLocal() as db:
        assert requeue_stale(db, now) == 1
        db.commit()


def test_config_imports_at_docker_path(tmp_path):
    from pathlib import Path

    import app.config as config

    assert (config.resource_directory("knowledge") / "legal" / "records.json").is_file()
    namespace = {"__file__": "/app/app/config.py", "__name__": "docker_config_regression"}
    code = Path(config.__file__).read_text()
    exec(compile(code, namespace["__file__"], "exec"), namespace)
    settings = namespace["Settings"](_env_file=None, templates_dir=tmp_path, knowledge_dir=tmp_path)
    assert settings.templates_dir == tmp_path
    assert settings.knowledge_dir == tmp_path
