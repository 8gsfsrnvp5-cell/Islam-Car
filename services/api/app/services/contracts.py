"""Договоры: проверки перед подписанием, подписание, пересчёт остатка."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    Car,
    CarStatus,
    Client,
    CompanySettings,
    Contract,
    ContractStatus,
    OwnershipStatus,
    PartyType,
    Payment,
    PaymentStatus,
    ScheduleItem,
    SellerRegime,
)
from app.services.common import today
from app.services.ledger import LedgerSummary, compute_ledger
from app.services.schedule import Terms, build_schedule, validate_terms


@dataclass
class Check:
    code: str
    ok: bool
    message: str
    blocking: bool = True


@dataclass
class CheckReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, code: str, ok: bool, message: str, blocking: bool = True) -> None:
        self.checks.append(Check(code, ok, message, blocking))

    @property
    def can_sign(self) -> bool:
        return all(c.ok for c in self.checks if c.blocking)


def get_company(db: Session) -> CompanySettings:
    settings = db.get(CompanySettings, 1)
    if settings is None:
        settings = CompanySettings(id=1)
        db.add(settings)
        db.flush()
    return settings


def is_consumer_deal(seller: SellerRegime, buyer: PartyType) -> bool:
    """Предприниматель продаёт физическому лицу — сделка подпадает под защиту прав потребителей."""
    return seller in (SellerRegime.ip, SellerRegime.llc) and buyer == PartyType.individual


def terms_of(c: Contract) -> Terms:
    return Terms(c.purchase_price_kopecks, c.sale_price_kopecks, c.down_payment_kopecks,
                 c.term_months, c.contract_date, c.first_payment_date)


def apply_terms(c: Contract, t: Terms) -> None:
    """Пересобирает финансовые поля и график черновика."""
    planned = build_schedule(t)
    c.purchase_price_kopecks = t.purchase_price_kopecks
    c.sale_price_kopecks = t.sale_price_kopecks
    c.markup_kopecks = t.markup_kopecks
    c.down_payment_kopecks = t.down_payment_kopecks
    c.financed_kopecks = t.financed_kopecks
    c.term_months = t.term_months
    c.contract_date = t.contract_date
    c.first_payment_date = t.first_payment_date
    installments = [p for p in planned if p.kind == "installment"]
    c.monthly_payment_kopecks = installments[0].amount_kopecks
    c.schedule.clear()
    c.schedule.extend(ScheduleItem(seq=p.seq, kind=p.kind, due_date=p.due_date,
                                   amount_kopecks=p.amount_kopecks) for p in planned)


def run_checks(db: Session, c: Contract) -> CheckReport:
    r = CheckReport()
    client: Client = c.client
    car: Car = c.car

    errors = validate_terms(terms_of(c))
    r.add("arithmetic", not errors, "Арифметика условий корректна" if not errors else "; ".join(errors))
    if not errors:
        total = sum(i.amount_kopecks for i in c.schedule)
        r.add("schedule_total", total == c.sale_price_kopecks,
              "Сумма графика равна цене продажи" if total == c.sale_price_kopecks
              else "Сумма графика не равна цене продажи — пересоздайте график")
    r.add("markup", c.markup_kopecks >= 0,
          "Цена продажи не ниже закупочной" if c.markup_kopecks >= 0
          else "Цена продажи ниже закупочной стоимости — сделка убыточна", blocking=False)

    # Мурабаха: продавец должен владеть автомобилем до продажи
    r.add("car_owned", car.ownership_status == OwnershipStatus.owned,
          "Автомобиль находится в собственности продавца" if car.ownership_status == OwnershipStatus.owned
          else "Автомобиль ещё не в собственности продавца — продавать его нельзя")
    r.add("car_vin", bool(car.vin), "VIN указан" if car.vin else "В карточке автомобиля не указан VIN")
    r.add("car_purchase_document", bool(car.purchase_document.strip()),
          "Документ о покупке автомобиля указан" if car.purchase_document.strip()
          else "Не указан документ, подтверждающий покупку автомобиля продавцом")
    busy = car.status == CarStatus.sold or db.scalar(
        select(func.count()).select_from(Contract).where(
            Contract.car_id == car.id, Contract.id != c.id,
            Contract.status.in_([ContractStatus.signed, ContractStatus.completed])))
    r.add("car_free", not busy, "Автомобиль не продан по другому договору" if not busy
          else "Автомобиль уже продан по другому договору")

    r.add("client_verified", client.identity_verified,
          "Личность покупателя проверена" if client.identity_verified
          else "Личность покупателя не подтверждена сотрудником")
    missing = missing_client_fields(client)
    r.add("client_requisites", not missing,
          "Реквизиты покупателя заполнены" if not missing else "Не заполнено: " + ", ".join(missing))

    company = get_company(db)
    seller_missing = [label for label, value in (
        ("наименование/ФИО продавца", company.seller_name), ("ИНН продавца", company.seller_inn),
        ("адрес продавца", company.seller_address)) if not value.strip()]
    r.add("seller_requisites", not seller_missing,
          "Реквизиты продавца заполнены" if not seller_missing
          else "В настройках не заполнено: " + ", ".join(seller_missing))

    if c.is_consumer_deal:
        r.add("consumer_regime", True,
              "Потребительская сделка: применяются требования Закона о защите прав потребителей. "
              "Текст договора должен быть утверждён юристом.", blocking=False)
    if c.seller_regime == SellerRegime.individual_one_off:
        r.add("seller_regime", True,
              "Режим «разовая продажа личного имущества». Регулярные продажи в этом режиме недопустимы — "
              "при систематической деятельности нужна регистрация ИП/ООО.", blocking=False)
    r.add("no_interest", c.no_interest_on_delay,
          "Проценты и штрафы за просрочку не начисляются" if c.no_interest_on_delay
          else "Договор допускает начисления за просрочку — недопустимо для модели")
    return r


def missing_client_fields(client: Client) -> list[str]:
    need: list[tuple[str, str]] = [("ФИО/наименование", client.full_name), ("телефон", client.phone),
                                   ("адрес", client.address)]
    if client.party_type == PartyType.individual:
        need += [("паспорт", client.passport_number), ("кем выдан паспорт", client.passport_issued_by)]
        if client.passport_issue_date is None:
            need.append(("дата выдачи паспорта", ""))
        if client.birth_date is None:
            need.append(("дата рождения", ""))
    elif client.party_type == PartyType.ip:
        need += [("ИНН", client.inn), ("ОГРНИП", client.ogrn)]
    else:
        need += [("ИНН", client.inn), ("ОГРН", client.ogrn), ("КПП", client.kpp),
                 ("представитель", client.representative)]
    return [label for label, value in need if not str(value).strip()]


def next_contract_number(db: Session, contract_date: date) -> str:
    company = db.scalar(select(CompanySettings).where(CompanySettings.id == 1).with_for_update())
    if company is None:
        company = get_company(db)
    seq = company.next_contract_seq
    company.next_contract_seq = seq + 1
    return f"{company.contract_prefix}-{contract_date.year}-{seq:04d}"


def sign(db: Session, c: Contract, signed_on: date, user_id) -> CheckReport:
    if c.status != ContractStatus.draft:
        raise HTTPException(409, "Подписать можно только черновик договора")
    report = run_checks(db, c)
    if not report.can_sign:
        return report
    c.number = next_contract_number(db, c.contract_date)
    c.status = ContractStatus.signed
    c.signed_at = signed_on
    c.signed_confirmed_by = user_id
    c.car.status = CarStatus.sold
    c.car.is_published = False
    if c.application_id:
        app_ = db.get(Application, c.application_id)
        if app_ and app_.status != ApplicationStatus.converted:
            message = "Договор заключён. Доступ к личному кабинету выдаст менеджер."
            db.add(ApplicationEvent(application_id=app_.id, from_status=app_.status.value,
                                    to_status=ApplicationStatus.converted.value,
                                    public_message=message, actor_user_id=user_id))
            app_.status = ApplicationStatus.converted
            app_.public_message = message
    return report


def confirmed_total(db: Session, contract_id) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Payment.amount_kopecks), 0))
        .where(Payment.contract_id == contract_id, Payment.status == PaymentStatus.confirmed)) or 0


def ledger_for(db: Session, c: Contract, on: date | None = None) -> LedgerSummary:
    items = [(i.seq, i.kind.value, i.due_date, i.amount_kopecks) for i in c.schedule]
    return compute_ledger(items, confirmed_total(db, c.id), on or today())


def sync_completion(db: Session, c: Contract) -> None:
    """Закрывает договор при полной оплате и переоткрывает его, если платёж сторнирован."""
    if c.status not in (ContractStatus.signed, ContractStatus.completed):
        return
    outstanding = ledger_for(db, c).outstanding_kopecks
    if outstanding == 0 and c.status == ContractStatus.signed:
        c.status = ContractStatus.completed
        c.completed_at = datetime.now(UTC)
    elif outstanding > 0 and c.status == ContractStatus.completed:
        c.status = ContractStatus.signed
        c.completed_at = None
