"""Smoke-check a fresh disposable Docker stack; never run against a working database.

Only CI sets ISLAMCAR_DISPOSABLE_STACK=1. The Windows launcher never runs this script.
"""
import copy
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from urllib.parse import urlsplit


class Api:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, path, data=None, method=None, expected=200):
        payload = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=payload, method=method,
                                     headers={'Content-Type': 'application/json', 'Origin': self.base})
        try:
            response = self.opener.open(req, timeout=15)
        except urllib.error.HTTPError as exc:
            assert exc.code == expected, f'{path}: {exc.code}, {exc.read().decode()}'
            return None
        with response:
            assert response.status == expected, path
            body = response.read()
            return json.loads(body) if response.headers.get_content_type() == 'application/json' else body


def main():
    if os.environ.get('ISLAMCAR_DISPOSABLE_STACK') != '1':
        raise SystemExit('Refusing: this script creates CI fixtures and requires a disposable stack.')
    admin, buyer = Api('http://localhost:3001'), Api('http://localhost:3000')
    for api in (admin, buyer):
        deadline = time.monotonic() + 180
        while True:
            try:
                assert api.request('/api/health')['status'] == 'ok'
                break
            except (OSError, AssertionError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
    # Fail before creating anything if the target contains business records.
    admin.request('/api/auth/admin/login', {'login': 'ci-owner@example.test',
                                          'password': os.environ['ISLAMCAR_CHECK_PASSWORD']})
    assert admin.request('/api/auth/admin/me')['role'] == 'owner'
    assert admin.request('/api/admin/contracts') == []
    assert admin.request('/api/admin/clients') == []
    assert admin.request('/api/admin/cars') == []
    assert buyer.request('/')
    assert buyer.request('/login')
    assert admin.request('/login')
    admin.request('/api/admin/settings', {'seller_regime': 'ip', 'seller_name': 'CI ONLY seller',
                                        'seller_inn': '000000000000', 'seller_address': 'CI ONLY address'}, method='PUT')
    today = date.today()
    car = admin.request('/api/admin/cars', {
        'make': 'CI ONLY', 'model': 'Smoke', 'year': today.year, 'vin': 'DEM00000000000001',
        'ownership_status': 'owned', 'status': 'available', 'purchase_price_kopecks': 100_000_000,
        'purchase_date': today.isoformat(), 'purchase_document': 'CI ONLY fixture',
        'sale_price_kopecks': 120_000_000, 'min_down_payment_kopecks': 20_000_000,
        'max_term_months': 12}, expected=201)
    client = admin.request('/api/admin/clients', {
        'full_name': 'CI ONLY buyer', 'phone': '+79000000001', 'address': 'CI ONLY address',
        'birth_date': '1990-01-01', 'passport_number': '0000 000000',
        'passport_issued_by': 'CI ONLY fixture', 'passport_issue_date': '2010-01-01'}, expected=201)
    admin.request(f"/api/admin/clients/{client['id']}/verify", method='POST')
    contract = admin.request('/api/admin/contracts', {
        'client_id': client['id'], 'car_id': car['id'], 'sale_price_kopecks': 120_000_000,
        'down_payment_kopecks': 20_000_000, 'term_months': 12, 'contract_date': today.isoformat(),
        'first_payment_date': (today + timedelta(days=30)).isoformat()}, expected=201)
    admin.request(f"/api/admin/contracts/{contract['id']}/sign",
                  {'signed_on': today.isoformat(), 'confirm_paper_signed': True})
    access = admin.request(f"/api/admin/clients/{client['id']}/access", method='POST')
    token = urlsplit(access['activation_path']).query.removeprefix('token=')
    buyer.request('/api/auth/client/activate', {'token': token, 'password': os.environ['ISLAMCAR_CHECK_PASSWORD']})
    buyer.request('/api/auth/client/login', {'login': access['login'], 'password': os.environ['ISLAMCAR_CHECK_PASSWORD']})
    assert buyer.request('/api/auth/client/me')['phone'] == '+79000000001'
    assert buyer.request('/api/client/contracts')[0]['id'] == contract['id']
    assert buyer.request('/cabinet')
    # Realm-specific cookie names and realm values cannot be interchanged.
    buyer.request('/api/admin/contracts', expected=401)
    admin.request('/api/client/contracts', expected=401)
    admin_cookie = copy.copy(next(c for c in admin.jar if c.name == 'ic_admin_session'))
    buyer_cookie = copy.copy(next(c for c in buyer.jar if c.name == 'ic_client_session'))
    admin_cookie.name = 'ic_client_session'
    buyer_cookie.name = 'ic_admin_session'
    buyer.jar.set_cookie(admin_cookie)
    admin.jar.set_cookie(buyer_cookie)
    buyer.request('/api/auth/client/me', expected=401)
    admin.request('/api/auth/admin/me', expected=401)
    print('Docker stack: admin login, client activation/login/cabinet and realm isolation passed.')


if __name__ == '__main__':
    main()
