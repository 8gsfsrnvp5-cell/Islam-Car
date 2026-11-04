"""Проверка договора на соответствие принципам мурабахи по библиотеке исламского финансирования.

Автоматические проверки показывают факты из данных системы. Окончательное подтверждение соответствия
шариату даёт уполномоченный специалист — система его не заменяет.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.service import load_records, problems, review_for
from app.models import Addendum, AddendumStatus, Contract, OwnershipStatus, Pledge, PledgeStatus
from app.services.common import today
from app.services.contracts import ledger_for


def evaluate(db: Session, c: Contract) -> dict:
    on = today()
    ledger = ledger_for(db, c, on)
    car = c.car
    addenda = db.scalars(select(Addendum).where(Addendum.contract_id == c.id,
                                                Addendum.status == AddendumStatus.signed)).all()
    pledge = db.scalar(select(Pledge).where(Pledge.contract_id == c.id))

    def check(state: str, message: str) -> dict:
        return {"state": state, "message": message}

    ownership_ok = car.ownership_status == OwnershipStatus.owned and car.purchase_document.strip()
    purchase_before = car.purchase_date is None or car.purchase_date <= c.contract_date
    facts = {
        "ownership": check("ok" if ownership_ok and purchase_before else "problem",
                           "Автомобиль в собственности продавца, документ о покупке указан"
                           + (f", куплен {car.purchase_date:%d.%m.%Y} — до договора" if car.purchase_date else
                              " (дата покупки не указана)")
                           if ownership_ok and purchase_before else
                           "Нет подтверждения, что продавец владел автомобилем до продажи"),
        "cost_disclosure": check("ok" if c.disclose_cost_to_buyer else "problem",
                                 "Себестоимость и наценка раскрыты покупателю" if c.disclose_cost_to_buyer else
                                 "Себестоимость не раскрывается — для мурабахи это требуется"),
        "fixed_price": check("ok" if ledger.total_kopecks == c.sale_price_kopecks else "problem",
                             "Сумма графика равна окончательной цене договора" if ledger.total_kopecks ==
                             c.sale_price_kopecks else "Сумма графика отличается от цены договора"),
        "no_late_increase": check("ok" if c.no_interest_on_delay and ledger.total_kopecks == c.sale_price_kopecks
                                  else "problem",
                                  "Проценты и штрафы за просрочку не начисляются, долг не растёт"
                                  if c.no_interest_on_delay else "Договор допускает начисления за просрочку"),
        "security": check("info", "Залог: " + ({
            PledgeStatus.registered: "зарегистрирован", PledgeStatus.planned: "планируется",
            PledgeStatus.not_required: "не оформляется", PledgeStatus.released: "прекращён"}.get(
                pledge.status, pledge.status.value) if pledge else "карточка не создана")),
        "rescheduling": check("ok" if all(sum(r["amount_kopecks"] for r in a.new_schedule) == c.sale_price_kopecks
                                          for a in addenda) else "problem",
                              f"Изменений графика: {len(addenda)}; цена при изменениях не увеличивалась"
                              if addenda else "График не изменялся"),
        "real_asset": check("ok" if car.vin and car.purchase_document.strip() else "problem",
                            "Товар идентифицирован (VIN) и приобретён по документу. Убедитесь, что автомобиль "
                            "не куплен у самого покупателя (обратный выкуп)" if car.vin
                            else "Товар не идентифицирован (нет VIN)"),
    }

    records = [r for r in load_records() if r.library == "islamic-finance"]
    items = []
    for rec in records:
        review = review_for(db, rec)
        fact = facts.get(rec.check or "", check("info", "Автоматической проверки нет — оценивает специалист"))
        items.append({"code": rec.code, "title": rec.title, "summary": rec.summary, "source": rec.source_hint,
                      "state": fact["state"], "message": fact["message"],
                      "rule_confirmed": review is not None and review.status == "approved",
                      "rule_problems": problems(rec, review, on)})
    failed = [i for i in items if i["state"] == "problem"]
    confirmed = sum(1 for i in items if i["rule_confirmed"])
    return {
        "items": items, "failed": len(failed), "rules_confirmed": confirmed, "rules_total": len(items),
        "verdict": ("Есть нарушения принципов мурабахи — требуется решение специалиста" if failed else
                    "Автоматические проверки пройдены"),
        "final_note": "Окончательное подтверждение соответствия шариату даёт уполномоченный специалист по исламскому "
                      f"финансированию. Правил библиотеки подтверждено специалистом: {confirmed} из {len(items)}.",
    }
