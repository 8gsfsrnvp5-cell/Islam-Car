"""Схема базы данных Islamic Car.

Деньги — целые копейки (BigInteger). Первичные ключи — UUID, чтобы не раскрывать
объёмы бизнеса последовательными номерами. Записи о деньгах не удаляются.
"""

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, native_enum=False, length=32, validate_strings=True,
                values_callable=lambda e: [m.value for m in e])


class Role(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    manager = "manager"
    accountant = "accountant"
    client = "client"


class Realm(enum.StrEnum):
    admin = "admin"
    client = "client"


class OwnershipStatus(enum.StrEnum):
    owned = "owned"            # в собственности продавца, может быть передан
    purchasing = "purchasing"  # в процессе закупки, продать пока нельзя


class CarStatus(enum.StrEnum):
    draft = "draft"
    available = "available"
    reserved = "reserved"
    sold = "sold"
    archived = "archived"


class ApplicationKind(enum.StrEnum):
    catalog = "catalog"            # заявка на автомобиль из каталога
    custom_order = "custom_order"  # заказ автомобиля, которого нет в каталоге


class ApplicationStatus(enum.StrEnum):
    new = "new"
    in_progress = "in_progress"
    info_requested = "info_requested"
    offer_made = "offer_made"
    converted = "converted"  # по заявке заключён договор
    rejected = "rejected"
    withdrawn = "withdrawn"


class PartyType(enum.StrEnum):
    individual = "individual"  # физическое лицо
    ip = "ip"                  # индивидуальный предприниматель
    llc = "llc"                # ООО


class SellerRegime(enum.StrEnum):
    individual_one_off = "individual_one_off"  # разовая продажа личного имущества
    ip = "ip"
    llc = "llc"


class ContractStatus(enum.StrEnum):
    draft = "draft"
    signed = "signed"        # действующий
    completed = "completed"  # обязательства исполнены полностью
    cancelled = "cancelled"  # черновик отменён до подписания


class ScheduleKind(enum.StrEnum):
    down_payment = "down_payment"
    installment = "installment"


class PaymentStatus(enum.StrEnum):
    confirmed = "confirmed"
    reversed = "reversed"


class PaymentMethod(enum.StrEnum):
    bank_transfer = "bank_transfer"
    cash = "cash"
    card = "card"
    other = "other"


class PaymentReportStatus(enum.StrEnum):
    pending = "pending"
    matched = "matched"
    rejected = "rejected"


class ThreadTopic(enum.StrEnum):
    general = "general"
    payment_difficulty = "payment_difficulty"
    schedule_change = "schedule_change"
    early_repayment = "early_repayment"
    documents = "documents"


class ThreadStatus(enum.StrEnum):
    open = "open"
    answered = "answered"
    closed = "closed"


class Audience(enum.StrEnum):
    staff = "staff"
    client = "client"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(str_enum(Role))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped["Client | None"] = relationship(back_populates="user", foreign_keys=[client_id])


class Session_(Base):
    """Серверная сессия: в cookie лежит случайный токен, в базе — только его хеш."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    realm: Mapped[Realm] = mapped_column(str_enum(Realm))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship()


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(120), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ActivationToken(Base):
    """Одноразовая ссылка для установки пароля покупателем (выдаётся сотрудником)."""

    __tablename__ = "activation_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompanySettings(Base):
    """Одна строка: режим продавца, реквизиты для оплаты, счётчик номеров договоров."""

    __tablename__ = "company_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    seller_regime: Mapped[SellerRegime] = mapped_column(str_enum(SellerRegime), default=SellerRegime.ip)
    seller_name: Mapped[str] = mapped_column(String(300), default="")
    seller_inn: Mapped[str] = mapped_column(String(12), default="")
    seller_ogrn: Mapped[str] = mapped_column(String(15), default="")
    seller_address: Mapped[str] = mapped_column(String(500), default="")
    support_phone: Mapped[str] = mapped_column(String(32), default="")
    bank_payee: Mapped[str] = mapped_column(String(300), default="")
    bank_name: Mapped[str] = mapped_column(String(300), default="")
    bank_bik: Mapped[str] = mapped_column(String(9), default="")
    bank_account: Mapped[str] = mapped_column(String(20), default="")
    bank_corr_account: Mapped[str] = mapped_column(String(20), default="")
    payment_purpose_hint: Mapped[str] = mapped_column(String(300), default="Оплата по договору № {number}")
    contract_prefix: Mapped[str] = mapped_column(String(16), default="IC")
    next_contract_seq: Mapped[int] = mapped_column(Integer, default=1)
    # Время и частота сообщений клиентам (параметры по ст. 7 230-ФЗ, требуют проверки юристом)
    communication_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Car(Base):
    __tablename__ = "cars"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vin: Mapped[str | None] = mapped_column(String(17), unique=True, index=True)
    make: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(80), index=True)
    year: Mapped[int] = mapped_column(Integer)
    mileage_km: Mapped[int] = mapped_column(Integer, default=0)
    body_type: Mapped[str] = mapped_column(String(60), default="")
    engine: Mapped[str] = mapped_column(String(120), default="")
    transmission: Mapped[str] = mapped_column(String(60), default="")
    drive: Mapped[str] = mapped_column(String(60), default="")
    color: Mapped[str] = mapped_column(String(60), default="")
    trim: Mapped[str] = mapped_column(Text, default="")
    condition: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")

    ownership_status: Mapped[OwnershipStatus] = mapped_column(
        str_enum(OwnershipStatus), default=OwnershipStatus.purchasing)
    status: Mapped[CarStatus] = mapped_column(str_enum(CarStatus), default=CarStatus.draft, index=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Коммерческая тайна: только для сотрудников
    purchase_price_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_document: Mapped[str] = mapped_column(String(300), default="")

    # Публичные условия
    sale_price_kopecks: Mapped[int] = mapped_column(BigInteger)
    min_down_payment_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    max_term_months: Mapped[int | None] = mapped_column(Integer)

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    photos: Mapped[list["CarPhoto"]] = relationship(
        back_populates="car", order_by="CarPhoto.position", cascade="all, delete-orphan")


class CarPhoto(Base):
    __tablename__ = "car_photos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    car: Mapped[Car] = relationship(back_populates="photos")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    party_type: Mapped[PartyType] = mapped_column(str_enum(PartyType), default=PartyType.individual)
    full_name: Mapped[str] = mapped_column(String(300), index=True)
    phone: Mapped[str] = mapped_column(String(16), index=True)
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    birth_date: Mapped[date | None] = mapped_column(Date)
    passport_number: Mapped[str] = mapped_column(String(20), default="")
    passport_issued_by: Mapped[str] = mapped_column(String(300), default="")
    passport_issue_date: Mapped[date | None] = mapped_column(Date)
    inn: Mapped[str] = mapped_column(String(12), default="")
    ogrn: Mapped[str] = mapped_column(String(15), default="")
    kpp: Mapped[str] = mapped_column(String(9), default="")
    representative: Mapped[str] = mapped_column(String(300), default="")
    timezone: Mapped[str] = mapped_column(String(40), default="Europe/Moscow")
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    identity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_clients_identity_verified_by"))
    # Сведения о долге отправляются только на подтверждённые сотрудником контакты
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User | None] = relationship(back_populates="client", foreign_keys=[User.client_id])


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[ApplicationKind] = mapped_column(str_enum(ApplicationKind))
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus), default=ApplicationStatus.new, index=True)
    car_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cars.id"))
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(16), index=True)
    desired_down_payment_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    desired_term_months: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    # Поля заказа автомобиля, которого нет в каталоге
    wanted_make: Mapped[str] = mapped_column(String(80), default="")
    wanted_model: Mapped[str] = mapped_column(String(80), default="")
    wanted_year: Mapped[int | None] = mapped_column(Integer)
    wanted_trim: Mapped[str] = mapped_column(Text, default="")
    max_budget_kopecks: Mapped[int | None] = mapped_column(BigInteger)

    consent_personal_data: Mapped[bool] = mapped_column(Boolean)
    consent_version: Mapped[str] = mapped_column(String(32))
    source_ip_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # антиспам, без хранения IP
    public_message: Mapped[str] = mapped_column(Text, default="")
    internal_note: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    car: Mapped[Car | None] = relationship()
    events: Mapped[list["ApplicationEvent"]] = relationship(
        order_by="ApplicationEvent.created_at", cascade="all, delete-orphan")


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    public_message: Mapped[str] = mapped_column(Text, default="")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[ContractStatus] = mapped_column(
        str_enum(ContractStatus), default=ContractStatus.draft, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id"), index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id"))

    seller_regime: Mapped[SellerRegime] = mapped_column(str_enum(SellerRegime))
    buyer_type: Mapped[PartyType] = mapped_column(str_enum(PartyType))
    is_consumer_deal: Mapped[bool] = mapped_column(Boolean)

    purchase_price_kopecks: Mapped[int] = mapped_column(BigInteger)
    sale_price_kopecks: Mapped[int] = mapped_column(BigInteger)
    markup_kopecks: Mapped[int] = mapped_column(BigInteger)
    down_payment_kopecks: Mapped[int] = mapped_column(BigInteger)
    financed_kopecks: Mapped[int] = mapped_column(BigInteger)
    term_months: Mapped[int] = mapped_column(Integer)
    monthly_payment_kopecks: Mapped[int] = mapped_column(BigInteger)
    contract_date: Mapped[date] = mapped_column(Date)
    first_payment_date: Mapped[date] = mapped_column(Date)
    disclose_cost_to_buyer: Mapped[bool] = mapped_column(Boolean, default=True)
    # Без процентов, пеней и штрафов за просрочку — неизменяемое условие модели
    no_interest_on_delay: Mapped[bool] = mapped_column(Boolean, default=True)
    # Растёт при подписании дополнительного соглашения об изменении графика
    schedule_version: Mapped[int] = mapped_column(Integer, default=1)

    signed_at: Mapped[date | None] = mapped_column(Date)
    signed_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    client: Mapped[Client] = relationship()
    car: Mapped[Car] = relationship()
    schedule: Mapped[list["ScheduleItem"]] = relationship(
        order_by="ScheduleItem.seq", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(order_by="Payment.received_on")


class ScheduleItem(Base):
    __tablename__ = "schedule_items"
    __table_args__ = (UniqueConstraint("contract_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 0 — первоначальный взнос
    kind: Mapped[ScheduleKind] = mapped_column(str_enum(ScheduleKind))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)


class Payment(Base):
    """Поступление денег. Учитывается только подтверждённое сотрудником; не удаляется."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    received_on: Mapped[date] = mapped_column(Date, index=True)
    method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod))
    document_ref: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[PaymentStatus] = mapped_column(str_enum(PaymentStatus), default=PaymentStatus.confirmed)
    confirmed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str] = mapped_column(Text, default="")
    corrects_payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_reports.id"))


class PaymentReport(Base):
    """Сообщение покупателя «Я оплатил». На остаток долга не влияет."""

    __tablename__ = "payment_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    paid_on: Mapped[date] = mapped_column(Date)
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[PaymentReportStatus] = mapped_column(
        str_enum(PaymentReportStatus), default=PaymentReportStatus.pending, index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    spent_on: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(80))
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(Text, default="")
    car_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cars.id"))
    document_ref: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportThread(Base):
    __tablename__ = "support_threads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id"))
    topic: Mapped[ThreadTopic] = mapped_column(str_enum(ThreadTopic))
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[ThreadStatus] = mapped_column(str_enum(ThreadStatus), default=ThreadStatus.open, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    client: Mapped[Client] = relationship()
    messages: Mapped[list["SupportMessage"]] = relationship(order_by="SupportMessage.created_at")


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_threads.id"), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    from_staff: Mapped[bool] = mapped_column(Boolean)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[User] = relationship()


class Notification(Base):
    """Внутренние уведомления: для сотрудников (общие) или для конкретного покупателя."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audience: Mapped[Audience] = mapped_column(str_enum(Audience), index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Журнал действий. Только добавление записей."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ============================== Версия 2 ==============================


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Job(Base):
    """Очередь фоновых задач в PostgreSQL: переживает перезапуск, не требует Redis."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.queued, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str] = mapped_column(Text, default="")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    jobs_done: Mapped[int] = mapped_column(Integer, default=0)


class NotificationEvent(enum.StrEnum):
    before_due = "before_due"
    due_day = "due_day"
    overdue = "overdue"
    payment_confirmed = "payment_confirmed"


class Channel(enum.StrEnum):
    internal = "internal"  # уведомление в личном кабинете
    sms = "sms"
    email = "email"


class NotificationRule(Base):
    __tablename__ = "notification_rules"
    __table_args__ = (UniqueConstraint("event", "offset_days"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event: Mapped[NotificationEvent] = mapped_column(str_enum(NotificationEvent))
    offset_days: Mapped[int] = mapped_column(Integer, default=0)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConsentPurpose(enum.StrEnum):
    service = "service"      # сервисные сообщения по договору
    marketing = "marketing"  # реклама — отдельное согласие


class Consent(Base):
    """Каждое изменение согласия — новая запись; действует последняя."""

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel))
    purpose: Mapped[ConsentPurpose] = mapped_column(str_enum(ConsentPurpose), default=ConsentPurpose.service)
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(200))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageStatus(enum.StrEnum):
    scheduled = "scheduled"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"
    skipped = "skipped"


class OutboundMessage(Base):
    """Журнал всех сообщений клиентам. event_key защищает от повторной отправки."""

    __tablename__ = "outbound_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id"), index=True)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel))
    purpose: Mapped[NotificationEvent] = mapped_column(str_enum(NotificationEvent))
    event_key: Mapped[str] = mapped_column(String(200), unique=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    body: Mapped[str] = mapped_column(Text)
    address_masked: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[MessageStatus] = mapped_column(
        str_enum(MessageStatus), default=MessageStatus.scheduled, index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(40), default="")
    provider_message_id: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TemplateApproval(Base):
    """Утверждение шаблона юристом. Действительно только для точного содержимого файла (sha256)."""

    __tablename__ = "template_approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_code: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(20))
    content_sha256: Mapped[str] = mapped_column(String(64))
    lawyer_name: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentStatus(enum.StrEnum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    signed = "signed"
    cancelled = "cancelled"


class AddendumStatus(enum.StrEnum):
    draft = "draft"
    signed = "signed"
    cancelled = "cancelled"


class Addendum(Base):
    """Дополнительное соглашение об изменении графика. Цена договора не меняется."""

    __tablename__ = "addenda"
    __table_args__ = (UniqueConstraint("contract_id", "number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[AddendumStatus] = mapped_column(str_enum(AddendumStatus), default=AddendumStatus.draft)
    reason: Mapped[str] = mapped_column(Text, default="")
    thread_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("support_threads.id"))
    term_months: Mapped[int] = mapped_column(Integer)
    first_payment_date: Mapped[date] = mapped_column(Date)
    old_schedule: Mapped[list] = mapped_column(JSON, default=list)
    new_schedule: Mapped[list] = mapped_column(JSON, default=list)
    base_paid_kopecks: Mapped[int] = mapped_column(BigInteger)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    signed_on: Mapped[date | None] = mapped_column(Date)


class Document(Base):
    """Документ из шаблона. После подписания запись не изменяется."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id"), index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), index=True)
    addendum_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("addenda.id"))
    template_code: Mapped[str] = mapped_column(String(60))
    template_version: Mapped[str] = mapped_column(String(20))
    template_sha256: Mapped[str] = mapped_column(String(64))
    template_approved: Mapped[bool] = mapped_column(Boolean)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus), default=DocumentStatus.draft, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    body: Mapped[str] = mapped_column(Text)
    body_sha256: Mapped[str] = mapped_column(String(64))
    visible_to_client: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_on: Mapped[date | None] = mapped_column(Date)
    signed_recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    signed_file_name: Mapped[str] = mapped_column(String(120), default="")
    signed_file_type: Mapped[str] = mapped_column(String(40), default="")
    signed_file_sha256: Mapped[str] = mapped_column(String(64), default="")
    cancelled_reason: Mapped[str] = mapped_column(Text, default="")


class ScheduleHistory(Base):
    """Прежние версии графика — сохраняются при подписании дополнительного соглашения."""

    __tablename__ = "schedule_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    due_date: Mapped[date] = mapped_column(Date)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    replaced_by_addendum_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("addenda.id"))
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PledgeStatus(enum.StrEnum):
    planned = "planned"
    documents_prepared = "documents_prepared"
    submitted = "submitted"            # документы переданы нотариусу
    registered = "registered"          # уведомление внесено в реестр (подтверждено номером)
    release_required = "release_required"
    release_submitted = "release_submitted"
    released = "released"
    not_required = "not_required"


class Pledge(Base):
    """Внутренний контроль залога. Статусы отражают реальные действия, внесённые сотрудником."""

    __tablename__ = "pledges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), unique=True)
    status: Mapped[PledgeStatus] = mapped_column(str_enum(PledgeStatus), default=PledgeStatus.planned)
    registry_number: Mapped[str] = mapped_column(String(60), default="")
    registered_on: Mapped[date | None] = mapped_column(Date)
    notary: Mapped[str] = mapped_column(String(300), default="")
    release_number: Mapped[str] = mapped_column(String(60), default="")
    released_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    contract: Mapped[Contract] = relationship()


class InsuranceKind(enum.StrEnum):
    osago = "osago"
    kasko = "kasko"
    other = "other"


class InsurancePolicy(Base):
    __tablename__ = "insurance_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id"), index=True)
    kind: Mapped[InsuranceKind] = mapped_column(str_enum(InsuranceKind))
    number: Mapped[str] = mapped_column(String(60))
    insurer: Mapped[str] = mapped_column(String(200), default="")
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date, index=True)
    required_by_contract: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    car: Mapped[Car] = relationship()


class TaskStatus(enum.StrEnum):
    open = "open"
    done = "done"
    cancelled = "cancelled"


class StaffTask(Base):
    """Задачи сотрудникам: создаются вручную или фоновым контролем сроков."""

    __tablename__ = "staff_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus), default=TaskStatus.open, index=True)
    link: Mapped[str] = mapped_column(String(300), default="")
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    result_note: Mapped[str] = mapped_column(Text, default="")


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))    # backup | verify
    status: Mapped[str] = mapped_column(String(20))  # running | ok | failed | skipped
    file_name: Mapped[str] = mapped_column(String(200), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
