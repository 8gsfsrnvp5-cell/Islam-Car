"""Версия 4: импорт банковской выписки 1C и подтверждение поступлений сотрудником."""

from app.models import Role
from app.services.bank_import import mentions, norm, parse, parse_amount
from app.services.common import today
from tests.conftest import staff_client
from tests.helpers import COMPANY, RUB, signed_deal

OUR = COMPANY["bank_account"]


def statement(docs: list[dict], account: str = OUR, encoding: str = "cp1251") -> bytes:
    d = today().strftime("%d.%m.%Y")
    lines = ["1CClientBankExchange", "ВерсияФормата=1.03", f"Кодировка={'DOS' if encoding == 'cp866' else 'Windows'}",
             f"ДатаНачала={d}", f"ДатаКонца={d}", f"РасчСчет={account}", "СекцияРасчСчет", f"РасчСчет={account}",
             "КонецРасчСчет"]
    for doc in docs:
        lines.append("СекцияДокумент=Платежное поручение")
        lines += [f"{k}={v}" for k, v in doc.items()]
        lines.append("КонецДокумента")
    lines.append("КонецФайла")
    return "\r\n".join(lines).encode(encoding)


def incoming(number: str, amount: str, purpose: str, payer: str = "Иванов Иван Иванович", inn: str = "") -> dict:
    d = today().strftime("%d.%m.%Y")
    return {"Номер": number, "Дата": d, "Сумма": amount, "ПлательщикСчет": "40817810000000000001",
            "Плательщик1": payer, "ПлательщикИНН": inn, "ПолучательСчет": OUR, "ДатаПоступило": d,
            "НазначениеПлатежа": purpose}


def outgoing(number: str, amount: str) -> dict:
    d = today().strftime("%d.%m.%Y")
    return {"Номер": number, "Дата": d, "Сумма": amount, "ПлательщикСчет": OUR,
            "ПолучательСчет": "40702810000000000009", "ДатаСписано": d, "НазначениеПлатежа": "Оплата поставщику"}


def upload(c, content: bytes, name: str = "kl_to_1c.txt"):
    return c.post("/api/admin/bank/imports", files={"file": (name, content, "text/plain")})


def test_parser_units():
    assert parse_amount("600000.00") == 600_000 * RUB
    assert parse_amount("12,5") == 1250
    assert mentions(norm("Оплата по договору № IC-2026-0001 за ноябрь"), "IC-2026-0001")
    assert not mentions(norm("по договору IC-2026-00012"), "IC-2026-0001")
    st = parse(statement([incoming("7", "100.00", "Оплата")], encoding="cp866"))
    assert st.account == OUR and st.period_from == today() and st.docs[0].get("Плательщик1") == "Иванов Иван Иванович"


def test_import_suggest_confirm_and_reverse(admin):
    _, _, contract = signed_deal(admin)
    number = contract["number"]
    content = statement([
        incoming("101", "600000.00", f"Оплата по договору № {number}. Первоначальный взнос"),
        incoming("102", "1000.00", "Возврат обеспечительного платежа", payer="ООО Ромашка", inn="7700000000"),
        outgoing("55", "300.00"),
    ])
    r = upload(admin, content)
    assert r.status_code == 201, r.text
    imp = r.json()
    assert (imp["rows_total"], imp["rows_incoming"], imp["rows_new"]) == (3, 2, 2)
    assert upload(admin, content).status_code == 409  # тот же файл повторно

    txs = {t["doc_number"]: t for t in admin.get("/api/admin/bank/transactions?status=open").json()}
    assert set(txs) == {"101", "102"}
    assert txs["101"]["status"] == "suggested" and txs["101"]["match_contract_number"] == number
    assert any("договор" in reason for reason in txs["101"]["match_reasons"])
    assert txs["102"]["status"] == "new" and txs["102"]["match_contract_id"] is None

    # Платёж по договору не создан, пока сотрудник не подтвердил
    before = admin.get(f"/api/admin/contracts/{contract['id']}").json()
    assert not [p for p in before["payments"] if p["status"] == "confirmed"]

    r = admin.post(f"/api/admin/bank/transactions/{txs['101']['id']}/confirm", json={"contract_id": contract["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["payment"]["source"] == "bank_statement" and body["payment"]["document_ref"].startswith("п/п № 101")
    assert body["transaction"]["status"] == "confirmed"
    payment_id = body["payment"]["id"]
    r = admin.post(f"/api/admin/bank/transactions/{txs['101']['id']}/confirm", json={"contract_id": contract["id"]})
    assert r.status_code == 409

    # Та же операция в следующей выписке не дублируется
    r = upload(admin, statement([incoming("101", "600000.00", f"Оплата по договору № {number}. Первоначальный взнос"),
                                 incoming("103", "50000.00", f"Платёж по договору {number}")]), "next.txt")
    assert r.status_code == 201 and r.json()["rows_new"] == 1

    # Сторно возвращает поступление в работу
    r = admin.post(f"/api/admin/payments/{payment_id}/reverse", json={"reason": "Отнесено не к тому договору"})
    assert r.status_code == 200, r.text
    tx = next(t for t in admin.get("/api/admin/bank/transactions").json() if t["doc_number"] == "101")
    assert tx["status"] == "new" and tx["payment_id"] is None and "сторнирован" in tx["note"]
    r = admin.post(f"/api/admin/bank/transactions/{tx['id']}/confirm", json={"contract_id": contract["id"]})
    assert r.status_code == 200, r.text

    # Не относящееся к договорам поступление откладывается с причиной и может вернуться в работу
    r = admin.post(f"/api/admin/bank/transactions/{txs['102']['id']}/ignore", json={"reason": "Возврат от поставщика"})
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    r = admin.post(f"/api/admin/bank/transactions/{txs['102']['id']}/confirm", json={"contract_id": contract["id"]})
    assert r.status_code == 409
    assert admin.post(f"/api/admin/bank/transactions/{txs['102']['id']}/reopen").json()["status"] == "new"


def test_amount_over_outstanding_is_not_suggested_or_confirmed(admin):
    _, _, contract = signed_deal(admin)
    r = upload(admin, statement([incoming("9", "5000000.00", f"Оплата по договору № {contract['number']}")]))
    assert r.status_code == 201
    tx = admin.get("/api/admin/bank/transactions").json()[0]
    assert tx["status"] == "new" and tx["match_contract_id"] is None
    r = admin.post(f"/api/admin/bank/transactions/{tx['id']}/confirm", json={"contract_id": contract["id"]})
    assert r.status_code == 422


def test_rejects_foreign_account_and_wrong_format(admin):
    signed_deal(admin)
    r = upload(admin, statement([incoming("1", "10.00", "x")], account="40702810999999999999"))
    assert r.status_code == 422 and "по счёту" in r.json()["detail"]
    assert upload(admin, b"not a statement").status_code == 422


def test_bank_permissions_and_masking(admin):
    signed_deal(admin)
    assert upload(admin, statement([incoming("1", "10.00", "x", inn="770000000000")])).status_code == 201
    manager = staff_client("manager1", Role.manager)
    assert upload(manager, statement([incoming("2", "10.00", "y")])).status_code == 403
    accountant = staff_client("accountant1", Role.accountant)
    tx = accountant.get("/api/admin/bank/transactions").json()[0]
    r = manager.post(f"/api/admin/bank/transactions/{tx['id']}/ignore", json={"reason": "проверка"})
    assert r.status_code == 403
    assert tx["payer_inn"] == "скрыт" and tx["payer_account"] == "…0001"
    assert tx["payer_name"] == "Иванов Иван Иванович"  # нужно, чтобы отнести платёж к договору
