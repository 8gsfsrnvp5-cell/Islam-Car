"""Сквозной сценарий версии 1: автомобиль → каталог → заявка → договор → график → платёж → кабинет."""

from datetime import timedelta

from app.services.common import today
from tests.helpers import (
    RUB,
    buyer_session,
    confirm_payment,
    create_car,
    create_contract,
    create_verified_client,
    setup_company,
    sign,
    signed_deal,
)


def test_full_path_from_car_to_first_payment(admin, public):
    setup_company(admin)

    # 1. Администратор создаёт карточку автомобиля и публикует её
    car = create_car(admin)
    assert car["is_published"] and car["purchase_price_kopecks"] == 1_200_000 * RUB

    # 2. Автомобиль виден в каталоге с правильным статусом и без коммерческих данных
    catalog = public.get("/api/public/cars").json()
    assert [c["id"] for c in catalog] == [car["id"]]
    assert catalog[0]["availability"] == "in_stock"
    assert not any(k.startswith("purchase") for k in catalog[0])
    assert "vin" not in catalog[0] and catalog[0]["vin_tail"].endswith("5678")

    # 3. Клиент отправляет заявку без паспортных данных
    r = public.post("/api/public/applications", json={
        "kind": "catalog", "car_id": car["id"], "name": "Иван", "phone": "8 (900) 111-22-33",
        "desired_down_payment_kopecks": 600_000 * RUB, "desired_term_months": 20, "consent_personal_data": True,
    })
    assert r.status_code == 201, r.text
    token = r.json()["public_token"]

    # 4. Заявка сразу появляется у администратора, владелец получает уведомление
    apps = admin.get("/api/admin/applications").json()
    assert len(apps) == 1 and apps[0]["status"] == "new" and apps[0]["phone"] == "+79001112233"
    assert admin.get("/api/admin/notifications/unread-count").json()["unread"] == 1
    app_id = apps[0]["id"]

    # Клиент видит понятный статус по секретной ссылке
    r = admin.post(f"/api/admin/applications/{app_id}/status",
                   json={"status": "in_progress", "public_message": "Менеджер позвонит сегодня"})
    assert r.status_code == 200
    status = public.get(f"/api/public/applications/{token}").json()
    assert status["status"] == "in_progress" and status["public_message"] == "Менеджер позвонит сегодня"
    assert "phone" not in status and "name" not in status

    # 5. Клиент по заявке, проверка личности, договор
    client_id = admin.post(f"/api/admin/applications/{app_id}/client").json()["client_id"]
    r = admin.patch(f"/api/admin/clients/{client_id}", json={
        "full_name": "Иванов Иван Иванович", "address": "г. Тестовый, ул. Клиентская, 2",
        "birth_date": "1990-05-01", "passport_number": "0000 000000", "passport_issued_by": "Тестовым отделом",
        "passport_issue_date": "2015-06-01"})
    assert r.status_code == 200, r.text
    assert admin.post(f"/api/admin/clients/{client_id}/verify").status_code == 200

    draft = create_contract(admin, client_id, car["id"], application_id=app_id)
    assert draft["status"] == "draft" and draft["number"] is None
    assert draft["checks"]["can_sign"], draft["checks"]
    assert draft["markup_kopecks"] == 400_000 * RUB
    assert draft["monthly_payment_kopecks"] == 50_000 * RUB

    # Пока договор не подписан, кабинет выдать нельзя
    assert admin.post(f"/api/admin/clients/{client_id}/access").status_code == 409

    # 8. Подписание фиксирует график, номер, продажу автомобиля
    contract = sign(admin, draft)
    assert contract["status"] == "signed" and contract["number"].startswith(f"IC-{today().year}-")
    assert len(contract["schedule"]) == 21
    assert sum(i["amount_kopecks"] for i in contract["schedule"]) == 1_600_000 * RUB
    assert public.get("/api/public/cars").json() == []  # продан — снят с публикации
    assert public.get(f"/api/public/applications/{token}").json()["status"] == "converted"

    # 7, 9. Покупатель получает доступ и видит договор, сумму и срок
    buyer = buyer_session(admin, client_id)
    mine = buyer.get("/api/client/contracts").json()
    assert len(mine) == 1
    detail = buyer.get(f"/api/client/contracts/{contract['id']}").json()
    assert detail["ledger"]["outstanding_kopecks"] == 1_600_000 * RUB
    assert detail["ledger"]["next_due_kopecks"] == 600_000 * RUB  # первым идёт взнос
    assert detail["purchase_price_kopecks"] == 1_200_000 * RUB  # мурабаха: себестоимость раскрыта
    assert detail["no_interest_on_delay"] is True

    # 11, 12. Подтверждение первоначального взноса уменьшает остаток в обеих системах
    confirm_payment(admin, contract["id"], 600_000)
    admin_view = admin.get(f"/api/admin/contracts/{contract['id']}").json()
    buyer_view = buyer.get(f"/api/client/contracts/{contract['id']}").json()
    assert admin_view["ledger"]["outstanding_kopecks"] == buyer_view["ledger"]["outstanding_kopecks"] == 1_000_000 * RUB
    assert buyer_view["ledger"]["next_due_kopecks"] == 50_000 * RUB
    assert [p["amount_kopecks"] for p in buyer_view["payments"]] == [600_000 * RUB]
    notes = buyer.get("/api/client/notifications").json()
    assert any("получен и учтён" in n["title"] for n in notes)

    # Главный экран: деньги, долг и наценка не смешаны
    d = admin.get("/api/admin/dashboard").json()
    assert d["operations"]["active_contracts"] == 1 and d["operations"]["clients"] == 1
    assert d["money"]["contracted_volume_kopecks"] == 1_600_000 * RUB
    assert d["money"]["cash_received_period_kopecks"] == 600_000 * RUB
    assert d["money"]["receivables_kopecks"] == 1_000_000 * RUB
    assert d["money"]["overdue_kopecks"] == 0
    assert d["finance"]["gross_markup_kopecks"] == 400_000 * RUB
    assert d["finance"]["taxes"]["status"] == "not_configured"


def test_purchasing_car_is_labeled_and_cannot_be_sold(admin, public):
    setup_company(admin)
    car = create_car(admin, owned=False)
    listed = public.get("/api/public/cars").json()
    assert listed[0]["availability"] == "purchasing"  # не «в наличии», пока не в собственности
    client = create_verified_client(admin)
    draft = create_contract(admin, client["id"], car["id"])
    assert not draft["checks"]["can_sign"]
    failed = {c["code"] for c in draft["checks"]["items"] if not c["ok"]}
    assert "car_owned" in failed
    r = admin.post(f"/api/admin/contracts/{draft['id']}/sign",
                   json={"signed_on": draft["contract_date"], "confirm_paper_signed": True})
    assert r.status_code == 422


def test_unverified_client_blocks_signing(admin):
    setup_company(admin)
    car = create_car(admin)
    r = admin.post("/api/admin/clients", json={"full_name": "Петров Пётр", "phone": "+79002223344"})
    draft = create_contract(admin, r.json()["id"], car["id"])
    failed = {c["code"] for c in draft["checks"]["items"] if not c["ok"]}
    assert {"client_verified", "client_requisites"} <= failed


def test_draft_car_not_in_catalog(admin, public):
    r = admin.post("/api/admin/cars", json={"make": "Lada", "model": "Vesta", "year": 2024,
                                            "sale_price_kopecks": 900_000 * RUB})
    assert r.status_code == 201
    assert admin.post(f"/api/admin/cars/{r.json()['id']}/publish").status_code == 422
    assert public.get("/api/public/cars").json() == []
    assert public.get(f"/api/public/cars/{r.json()['id']}").status_code == 404


def test_custom_order_request(admin, public):
    r = public.post("/api/public/applications", json={
        "kind": "custom_order", "name": "Анна", "phone": "+7 912 000-00-01", "wanted_make": "Kia",
        "wanted_model": "K5", "wanted_year": 2023, "max_budget_kopecks": 2_500_000 * RUB,
        "desired_term_months": 24, "consent_personal_data": True})
    assert r.status_code == 201, r.text
    apps = admin.get("/api/admin/applications?kind=custom_order").json()
    assert apps[0]["wanted_model"] == "K5" and apps[0]["car"] is None


def test_application_validation(public):
    base = {"kind": "custom_order", "name": "Анна", "phone": "+79120000001", "wanted_make": "Kia",
            "wanted_model": "K5", "consent_personal_data": True}
    assert public.post("/api/public/applications", json={**base, "consent_personal_data": False}).status_code == 422
    assert public.post("/api/public/applications", json={**base, "phone": "12345"}).status_code == 422
    assert public.post("/api/public/applications", json={**base, "website": "spam"}).status_code == 400
    assert public.post("/api/public/applications", json={**base, "wanted_make": ""}).status_code == 422


def test_applicant_can_withdraw(admin, public):
    r = public.post("/api/public/applications", json={
        "kind": "custom_order", "name": "Анна", "phone": "+79120000001", "wanted_make": "Kia",
        "wanted_model": "K5", "consent_personal_data": True})
    token = r.json()["public_token"]
    assert public.post(f"/api/public/applications/{token}/withdraw").json()["status"] == "withdrawn"
    assert admin.get("/api/admin/applications").json()[0]["status"] == "withdrawn"


def test_signed_contract_is_immutable(admin):
    _, _, contract = signed_deal(admin)
    r = admin.patch(f"/api/admin/contracts/{contract['id']}", json={"term_months": 10})
    assert r.status_code == 409
    r = admin.patch(f"/api/admin/cars/{contract['car']['id']}", json={"sale_price_kopecks": 1})
    assert r.status_code == 409


def test_overdue_detected_and_paid_items_not_overdue(admin):
    # Договор 70 дней назад: взнос и два платежа уже должны были поступить
    start = today() - timedelta(days=70)
    _, _, contract = signed_deal(admin, contract_date=start)
    lg = admin.get(f"/api/admin/contracts/{contract['id']}").json()["ledger"]
    assert lg["overdue_items"] == 3
    assert lg["overdue_kopecks"] == (600_000 + 50_000 + 50_000) * RUB

    d = admin.get("/api/admin/dashboard").json()
    assert d["operations"]["problem_deals"] == 1 and d["problem_deals"][0]["days_overdue"] == 70

    confirm_payment(admin, contract["id"], 700_000, received_on=today())
    lg = admin.get(f"/api/admin/contracts/{contract['id']}").json()["ledger"]
    assert lg["overdue_kopecks"] == 0 and lg["overdue_items"] == 0
    statuses = [r["status"] for r in lg["rows"][:3]]
    assert statuses == ["paid", "paid", "paid"]
    # Просрочка не увеличила долг
    assert lg["outstanding_kopecks"] == 900_000 * RUB


def test_calendar_and_reports(admin):
    _, _, contract = signed_deal(admin)
    month = contract["schedule"][1]["due_date"][:7]
    cal = admin.get(f"/api/admin/calendar?month={month}").json()
    assert any(i["number"] == contract["number"] and i["amount_kopecks"] == 50_000 * RUB for i in cal["items"])
    csv_text = admin.get("/api/admin/reports/contracts.csv").text
    assert contract["number"] in csv_text and "1600000,00" in csv_text


def test_search_finds_by_vin_phone_and_number(admin):
    _, _, contract = signed_deal(admin)
    assert admin.get("/api/admin/search?q=12345678").json()["cars"]
    assert admin.get("/api/admin/search?q=9001112233").json()["clients"]
    found = admin.get(f"/api/admin/search?q={contract['number']}").json()["contracts"]
    assert found[0]["id"] == contract["id"]


def test_support_thread_round_trip(admin):
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    r = buyer.post("/api/client/threads", json={
        "topic": "payment_difficulty", "subject": "Задержка зарплаты",
        "body": "Прошу перенести платёж на неделю", "contract_id": contract["id"]})
    assert r.status_code == 201
    thread_id = r.json()["id"]
    staff_view = admin.get(f"/api/admin/threads/{thread_id}").json()
    assert staff_view["contract"]["number"] == contract["number"]  # менеджер видит историю договора
    admin.post(f"/api/admin/threads/{thread_id}/messages", json={"body": "Рассмотрим, перезвоним"})
    msgs = buyer.get(f"/api/client/threads/{thread_id}").json()["messages"]
    assert [m["from_staff"] for m in msgs] == [False, True]
    # Обращение не меняет договор автоматически
    assert admin.get(f"/api/admin/contracts/{contract['id']}").json()["term_months"] == 20
