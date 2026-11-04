"""Входные данные API. Суммы — целые копейки."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    ApplicationKind,
    ApplicationStatus,
    CarStatus,
    OwnershipStatus,
    PartyType,
    PaymentMethod,
    Role,
    SellerRegime,
    ThreadTopic,
)

MAX_KOPECKS = 10**13


def kop():
    return Field(ge=0, le=MAX_KOPECKS)


def opt_kop():
    return Field(default=None, ge=0, le=MAX_KOPECKS)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- Авторизация ---

class LoginIn(StrictModel):
    login: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)
    totp_code: str | None = Field(default=None, max_length=10)


class ActivateIn(StrictModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=200)


class ChangePasswordIn(StrictModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class TotpCodeIn(StrictModel):
    code: str = Field(min_length=6, max_length=10)


# --- Публичная часть ---

class ApplicationIn(StrictModel):
    kind: ApplicationKind
    name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=5, max_length=32)
    car_id: UUID | None = None
    desired_down_payment_kopecks: int | None = opt_kop()
    desired_term_months: int | None = Field(default=None, ge=1, le=120)
    comment: str = Field(default="", max_length=2000)
    wanted_make: str = Field(default="", max_length=80)
    wanted_model: str = Field(default="", max_length=80)
    wanted_year: int | None = Field(default=None, ge=1980, le=2100)
    wanted_trim: str = Field(default="", max_length=2000)
    max_budget_kopecks: int | None = opt_kop()
    consent_personal_data: bool
    website: str = Field(default="", max_length=200)  # ловушка для ботов: люди это поле не видят


# --- Автомобили ---

class CarIn(StrictModel):
    vin: str | None = Field(default=None, max_length=17)
    make: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=80)
    year: int = Field(ge=1980, le=2100)
    mileage_km: int = Field(default=0, ge=0, le=3_000_000)
    body_type: str = Field(default="", max_length=60)
    engine: str = Field(default="", max_length=120)
    transmission: str = Field(default="", max_length=60)
    drive: str = Field(default="", max_length=60)
    color: str = Field(default="", max_length=60)
    trim: str = Field(default="", max_length=4000)
    condition: str = Field(default="", max_length=4000)
    description: str = Field(default="", max_length=8000)
    ownership_status: OwnershipStatus = OwnershipStatus.purchasing
    status: CarStatus = CarStatus.draft
    purchase_price_kopecks: int | None = opt_kop()
    purchase_date: date | None = None
    purchase_document: str = Field(default="", max_length=300)
    purchased_from: str = Field(default="unknown", pattern=r"^(individual|company|unknown)$")
    sale_price_kopecks: int = Field(gt=0, le=10**13)
    min_down_payment_kopecks: int | None = opt_kop()
    max_term_months: int | None = Field(default=None, ge=1, le=120)


class CarPatch(StrictModel):
    vin: str | None = Field(default=None, max_length=17)
    make: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    year: int | None = Field(default=None, ge=1980, le=2100)
    mileage_km: int | None = Field(default=None, ge=0, le=3_000_000)
    body_type: str | None = Field(default=None, max_length=60)
    engine: str | None = Field(default=None, max_length=120)
    transmission: str | None = Field(default=None, max_length=60)
    drive: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=60)
    trim: str | None = Field(default=None, max_length=4000)
    condition: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=8000)
    ownership_status: OwnershipStatus | None = None
    status: CarStatus | None = None
    purchase_price_kopecks: int | None = opt_kop()
    purchase_date: date | None = None
    purchase_document: str | None = Field(default=None, max_length=300)
    purchased_from: str | None = Field(default=None, pattern=r"^(individual|company|unknown)$")
    sale_price_kopecks: int | None = Field(default=None, gt=0, le=10**13)
    min_down_payment_kopecks: int | None = opt_kop()
    max_term_months: int | None = Field(default=None, ge=1, le=120)


# --- Заявки и клиенты ---

class ApplicationStatusIn(StrictModel):
    status: ApplicationStatus
    public_message: str = Field(default="", max_length=2000)
    internal_note: str | None = Field(default=None, max_length=4000)


class ClientIn(StrictModel):
    party_type: PartyType = PartyType.individual
    full_name: str = Field(min_length=2, max_length=300)
    phone: str = Field(min_length=5, max_length=32)
    email: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=500)
    birth_date: date | None = None
    passport_number: str = Field(default="", max_length=20)
    passport_issued_by: str = Field(default="", max_length=300)
    passport_issue_date: date | None = None
    inn: str = Field(default="", max_length=12)
    ogrn: str = Field(default="", max_length=15)
    kpp: str = Field(default="", max_length=9)
    representative: str = Field(default="", max_length=300)
    timezone: str = Field(default="Europe/Moscow", max_length=40)
    notes: str = Field(default="", max_length=4000)


class ClientPatch(StrictModel):
    party_type: PartyType | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=300)
    phone: str | None = Field(default=None, min_length=5, max_length=32)
    email: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    birth_date: date | None = None
    passport_number: str | None = Field(default=None, max_length=20)
    passport_issued_by: str | None = Field(default=None, max_length=300)
    passport_issue_date: date | None = None
    inn: str | None = Field(default=None, max_length=12)
    ogrn: str | None = Field(default=None, max_length=15)
    kpp: str | None = Field(default=None, max_length=9)
    representative: str | None = Field(default=None, max_length=300)
    timezone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)


# --- Договоры и платежи ---

class TermsIn(StrictModel):
    sale_price_kopecks: int = Field(gt=0, le=10**13)
    down_payment_kopecks: int = kop()
    term_months: int = Field(ge=1, le=120)
    contract_date: date
    first_payment_date: date


class PreviewIn(TermsIn):
    car_id: UUID


class ContractIn(TermsIn):
    client_id: UUID
    car_id: UUID
    application_id: UUID | None = None
    disclose_cost_to_buyer: bool = True
    notes: str = Field(default="", max_length=4000)


class ContractPatch(StrictModel):
    sale_price_kopecks: int | None = Field(default=None, gt=0, le=10**13)
    down_payment_kopecks: int | None = opt_kop()
    term_months: int | None = Field(default=None, ge=1, le=120)
    contract_date: date | None = None
    first_payment_date: date | None = None
    disclose_cost_to_buyer: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)


class SignIn(StrictModel):
    signed_on: date
    confirm_paper_signed: bool = Field(description="Сотрудник подтверждает, что договор подписан сторонами")


class PaymentIn(StrictModel):
    contract_id: UUID
    amount_kopecks: int = Field(gt=0, le=10**13)
    received_on: date
    method: PaymentMethod
    document_ref: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=2000)
    report_id: UUID | None = None
    corrects_payment_id: UUID | None = None


class ReverseIn(StrictModel):
    reason: str = Field(min_length=5, max_length=2000)


class ReportReviewIn(StrictModel):
    note: str = Field(min_length=2, max_length=2000)


class PaymentReportIn(StrictModel):
    amount_kopecks: int = Field(gt=0, le=10**13)
    paid_on: date
    comment: str = Field(default="", max_length=2000)


class ExpenseIn(StrictModel):
    spent_on: date
    category: str = Field(min_length=2, max_length=80)
    amount_kopecks: int = Field(gt=0, le=10**13)
    description: str = Field(default="", max_length=2000)
    car_id: UUID | None = None
    document_ref: str = Field(default="", max_length=120)


# --- Обращения ---

class ThreadIn(StrictModel):
    topic: ThreadTopic = ThreadTopic.general
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=2, max_length=5000)
    contract_id: UUID | None = None


class MessageIn(StrictModel):
    body: str = Field(min_length=1, max_length=5000)


# --- Настройки и сотрудники ---

class CompanySettingsIn(StrictModel):
    seller_regime: SellerRegime
    seller_name: str = Field(default="", max_length=300)
    seller_inn: str = Field(default="", max_length=12)
    seller_ogrn: str = Field(default="", max_length=15)
    seller_address: str = Field(default="", max_length=500)
    support_phone: str = Field(default="", max_length=32)
    bank_payee: str = Field(default="", max_length=300)
    bank_name: str = Field(default="", max_length=300)
    bank_bik: str = Field(default="", max_length=9)
    bank_account: str = Field(default="", max_length=20)
    bank_corr_account: str = Field(default="", max_length=20)
    payment_purpose_hint: str = Field(default="Оплата по договору № {number}", max_length=300)
    contract_prefix: str = Field(default="IC", min_length=1, max_length=16, pattern=r"^[A-Za-zА-Яа-я0-9]+$")


class StaffUserIn(StrictModel):
    login: str = Field(min_length=3, max_length=120)
    full_name: str = Field(min_length=2, max_length=200)
    role: Role
    password: str = Field(max_length=200)


# --- Версия 2: документы, графики, уведомления, залоги, задачи ---

class TemplateApproveIn(StrictModel):
    lawyer_name: str = Field(min_length=3, max_length=200)
    note: str = Field(default="", max_length=2000)


class DocumentIn(StrictModel):
    template_code: str = Field(min_length=2, max_length=60)
    contract_id: UUID | None = None
    client_id: UUID | None = None
    car_id: UUID | None = None
    addendum_id: UUID | None = None
    params: dict[str, str | bool] = Field(default_factory=dict)


class ReasonIn(StrictModel):
    reason: str = Field(min_length=3, max_length=2000)


class AddendumIn(StrictModel):
    term_months: int = Field(ge=1, le=120)
    first_payment_date: date
    reason: str = Field(default="", max_length=2000)
    thread_id: UUID | None = None


class RuleIn(StrictModel):
    id: UUID | None = None
    event: str = Field(pattern=r"^(before_due|due_day|overdue|payment_confirmed)$")
    offset_days: int = Field(ge=0, le=60)
    channels: list[str] = Field(default_factory=list)
    enabled: bool = True


class RulesIn(StrictModel):
    rules: list[RuleIn]


class PolicyIn(StrictModel):
    weekday_from: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday_to: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekend_from: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekend_to: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    overdue_per_day: int = Field(ge=0, le=10)
    overdue_per_week: int = Field(ge=0, le=50)
    overdue_per_month: int = Field(ge=0, le=200)
    holidays: list[date] = Field(default_factory=list)


class ConsentIn(StrictModel):
    channel: str = Field(pattern=r"^(sms|email)$")
    granted: bool
    source: str = Field(min_length=3, max_length=200)


class ContactVerifyIn(StrictModel):
    contact: str = Field(pattern=r"^(phone|email)$")
    verified: bool = True


class PledgeIn(StrictModel):
    status: str = Field(pattern=r"^(planned|documents_prepared|submitted|registered|release_required|"
                                r"release_submitted|released|not_required)$")
    registry_number: str = Field(default="", max_length=60)
    registered_on: date | None = None
    notary: str = Field(default="", max_length=300)
    release_number: str = Field(default="", max_length=60)
    released_on: date | None = None
    notes: str = Field(default="", max_length=4000)


class InsuranceIn(StrictModel):
    car_id: UUID
    contract_id: UUID | None = None
    kind: str = Field(pattern=r"^(osago|kasko|other)$")
    number: str = Field(min_length=3, max_length=60)
    insurer: str = Field(default="", max_length=200)
    valid_from: date
    valid_to: date
    required_by_contract: bool = False
    notes: str = Field(default="", max_length=2000)


class TaskIn(StrictModel):
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=4000)
    due_date: date | None = None
    link: str = Field(default="", max_length=300)


class TaskDoneIn(StrictModel):
    note: str = Field(default="", max_length=2000)


class ClientConsentIn(StrictModel):
    channel: str = Field(pattern=r"^(sms|email)$")
    granted: bool
