"""Специализированные агенты (версии 3 и 4)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, Finding
from app.documents.registry import load_templates
from app.knowledge.service import assess, load_records, review_for
from app.models import (
    AgentRun,
    Application,
    ApplicationKind,
    ApplicationStatus,
    BankTransaction,
    Car,
    CarStatus,
    Channel,
    Contract,
    ContractStatus,
    MessageStatus,
    OutboundMessage,
    OwnershipStatus,
    Payment,
    PaymentIntent,
    PaymentReport,
    PaymentReportStatus,
    PaymentStatus,
    StaffTask,
    TaskStatus,
    TaxCalendarEvent,
    WorkerHeartbeat,
)
from app.services import car_checks
from app.services.accounting import PARAMS, calculate
from app.services.contracts import get_company
from app.services.dashboard import live_ledgers
from app.services.document_audit import audit_documents
from app.services.messaging import address_for, has_consent
from app.services.notify import rub


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class PaymentsAgent(Agent):
    code = "payments"
    title = "Платёжный агент"
    description = "Графики, поступления, просрочки и сверка сообщений об оплате"
    permissions = ["create:tasks"]
    reads = ["договоры", "платежи", "сообщения «Я оплатил»"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        out: list[Finding] = []
        stale = db.execute(select(PaymentReport, Contract.number, Contract.id).join(
            Contract, Contract.id == PaymentReport.contract_id).where(
            PaymentReport.status == PaymentReportStatus.pending,
            PaymentReport.created_at < ctx.now - timedelta(days=2))).all()
        for report, number, cid in stale:
            out.append(Finding("warning", f"Сообщение об оплате по договору № {number} не сверено больше 2 дней",
                               f"{rub(report.amount_kopecks)} от {report.paid_on:%d.%m.%Y}", f"/contracts/{cid}",
                               suggestion="Сверить с банковской выпиской и подтвердить или отклонить"))
            ctx.create_task("payment_report", f"Сверить сообщение об оплате: договор № {number}",
                            f"{rub(report.amount_kopecks)} от {report.paid_on:%d.%m.%Y}", f"/contracts/{cid}",
                            f"payment_report:{report.id}", due=ctx.today)
        overdue = [(c, lg) for c, lg in live_ledgers(db, ctx.today) if lg.overdue_kopecks]
        if overdue:
            out.append(Finding("warning", f"Договоров с просрочкой: {len(overdue)}",
                               f"Просрочено всего {rub(sum(lg.overdue_kopecks for _, lg in overdue))}. "
                               "Проценты и штрафы не начисляются.", "/", suggestion="Связаться с покупателями"))
        for c, lg in live_ledgers(db, ctx.today):
            if c.status == ContractStatus.completed and lg.outstanding_kopecks > 0:
                out.append(Finding("critical", f"Договор № {c.number} закрыт, но остаток не нулевой",
                                   "Нарушена согласованность данных — проверить платежи", f"/contracts/{c.id}"))
        reversed_count = db.scalar(select(func.count()).select_from(Payment).where(
            Payment.status == PaymentStatus.reversed, Payment.reversed_at >= ctx.now - timedelta(days=7))) or 0
        if reversed_count:
            out.append(Finding("info", f"Сторнировано платежей за неделю: {reversed_count}", link="/payments"))
        waiting = db.scalar(select(func.count()).select_from(BankTransaction).where(
            BankTransaction.status.in_(("new", "suggested")),
            BankTransaction.received_on <= ctx.today - timedelta(days=2))) or 0
        if waiting:
            out.append(Finding("warning", f"Поступления из выписок без решения больше 2 дней: {waiting}",
                               "Пока сотрудник не подтвердил поступление, долг покупателя не уменьшается.", "/bank",
                               suggestion="Отнести поступления к договорам или отметить как не относящиеся"))
            ctx.create_task("bank_review", f"Разобрать поступления из выписок: {waiting}",
                            "Подтвердить договор по каждому поступлению или указать причину", "/bank",
                            f"bank_review:{ctx.today}", due=ctx.today)
        review = db.scalar(select(func.count()).select_from(PaymentIntent).where(
            PaymentIntent.status == "needs_review")) or 0
        if review:
            out.append(Finding("critical", f"Онлайн-оплаты требуют проверки: {review}",
                               "Деньги получены платёжным сервисом, но автоматически не учтены.", "/payments"))
        return out


class NotificationsAgent(Agent):
    code = "notifications"
    title = "Агент уведомлений"
    description = "Контроль доставки напоминаний и законных каналов связи"
    permissions = ["create:tasks"]
    reads = ["журнал сообщений", "согласия", "состояние обработчика"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        out: list[Finding] = []
        for c, lg in live_ledgers(db, ctx.today):
            if not lg.overdue_kopecks:
                continue
            allowed = [ch for ch in (Channel.sms, Channel.email)
                       if has_consent(db, c.client_id, ch) and address_for(c.client, ch)[0]]
            if not allowed:
                out.append(Finding("warning", f"Нет разрешённого канала для напоминаний: договор № {c.number}",
                                   f"{c.client.full_name}: нет согласия или подтверждённого контакта. Внешние "
                                   "напоминания о просрочке не отправляются.", f"/clients/{c.client_id}",
                                   refs=["legal.152fz.9", "legal.230fz.7"], suggestion="Позвонить покупателю"))
                ctx.create_task("no_channel", f"Позвонить покупателю: просрочка по договору № {c.number}",
                                "Внешние напоминания не отправляются — нет согласия или подтверждённого контакта.",
                                f"/clients/{c.client_id}", f"no_channel:{c.id}:{lg.oldest_overdue_date}", due=ctx.today)
        failed = db.scalar(select(func.count()).select_from(OutboundMessage).where(
            OutboundMessage.status == MessageStatus.failed, OutboundMessage.created_at >= ctx.now - timedelta(days=7)))
        if failed:
            out.append(Finding("warning", f"Не доставлено сообщений за неделю: {failed}", link="/notifications"))
        not_connected = db.scalar(select(func.count()).select_from(OutboundMessage).where(
            OutboundMessage.status == MessageStatus.skipped, OutboundMessage.status_reason == "Канал не подключён"))
        if not_connected:
            out.append(Finding("info", f"Сообщений пропущено из-за неподключённого канала: {not_connected}",
                               "Для SMS нужен договор с официальным поставщиком рассылок", "/notifications"))
        beat = db.scalar(select(func.max(WorkerHeartbeat.last_seen)))
        if beat is None or ctx.now - aware(beat) > timedelta(minutes=10):
            out.append(Finding("critical", "Фоновый обработчик не отвечает",
                               "Напоминания, контроль сроков и резервные копии не выполняются", "/notifications"))
        return out


class LegalAgent(Agent):
    code = "legal"
    title = "Юридический агент"
    description = "Нормы для шаблонов документов: источники, редакции, статус проверки юристом"
    permissions: list[str] = []
    reads = ["шаблоны документов", "юридическая библиотека"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        out: list[Finding] = []
        for tpl in load_templates().values():
            result = assess(db, tpl.legal_refs, ctx.today)
            bad = [i for i in result["items"] if not i["reliable"]]
            if not tpl.legal_refs:
                out.append(Finding("warning", f"Шаблон «{tpl.title}»: не указаны нормы", "Требуется проверка юриста",
                                   "/documents"))
            elif bad:
                out.append(Finding("warning", f"Шаблон «{tpl.title}»: {result['verdict']}",
                                   f"Не подтверждено норм: {len(bad)} из {len(result['items'])}. Например: "
                                   f"{bad[0]['title']} — {'; '.join(bad[0]['problems'][:2])}", "/documents",
                                   refs=[i["code"] for i in bad]))
            if tpl.lawyer_points:
                out.append(Finding("info", f"Шаблон «{tpl.title}»: вопросов юристу в тексте — {len(tpl.lawyer_points)}",
                                   link="/documents"))
        records = [r for r in load_records() if r.library == "legal"]
        expired = [r for r in records if r.effective_to and r.effective_to <= ctx.today]
        unreviewed = [r for r in records if review_for(db, r) is None]
        if expired:
            out.append(Finding("critical", f"Норм, утративших силу: {len(expired)}", link="/knowledge",
                               refs=[r.code for r in expired]))
        if unreviewed:
            out.append(Finding("warning", f"Юридическая библиотека: без заключения юриста — {len(unreviewed)} из "
                               f"{len(records)}", "Пока нормы не проверены, документы остаются проектами",
                               "/knowledge"))
        return out


class AccountingAgent(Agent):
    code = "accounting"
    title = "Бухгалтерский агент"
    description = "Налоговый профиль, утверждённые правила, налоговый календарь, оценка налога"
    permissions = ["create:tasks"]
    reads = ["налоговый профиль", "параметры правил", "налоговый календарь", "операции"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        out: list[Finding] = []
        co = get_company(db)
        if not co.tax_regime:
            out.append(Finding("warning", "Налоговый режим не выбран", "Расчёт налогов невозможен", "/accounting",
                               refs=["acc.nk.346_14"]))
        else:
            calc = calculate(db, ctx.today.replace(month=1, day=1), ctx.today)
            for r in calc["results"]:
                if r["status"] == "not_configured":
                    needed = [c for c, d in PARAMS.items() if co.tax_regime in d["regimes"]]
                    out.append(Finding("warning", f"{r['title']}: нет утверждённых параметров",
                                       "Нужно внести значения из официального источника и утвердить: "
                                       + ", ".join(PARAMS[c]["title"] for c in needed), "/accounting",
                                       refs=r["basis"]))
                elif r["status"] == "ok" and r["amount_kopecks"] is not None:
                    out.append(Finding("info", f"{r['title']} с начала года: {rub(r['amount_kopecks'])}",
                                       "Оценка для проверки бухгалтером", "/accounting", refs=r["basis"]))
        for e in db.scalars(select(TaxCalendarEvent).where(TaxCalendarEvent.status == "open")):
            days = (e.due_date - ctx.today).days
            if days < 0:
                out.append(Finding("critical", f"Просрочен налоговый срок: {e.title}",
                                   f"Срок был {e.due_date:%d.%m.%Y}", "/accounting",
                                   refs=[e.knowledge_code] if e.knowledge_code else []))
            elif days <= 7:
                out.append(Finding("warning", f"Налоговый срок через {days} дн.: {e.title}", link="/accounting",
                                   refs=[e.knowledge_code] if e.knowledge_code else []))
                ctx.create_task("tax_deadline", f"Налоговый срок {e.due_date:%d.%m.%Y}: {e.title}",
                                "Подготовить и проверить. Подача и уплата — только с подтверждения владельца.",
                                "/accounting", f"tax_deadline:{e.id}", due=e.due_date)
        return out


class FinanceAgent(Agent):
    code = "finance"
    title = "Финансовый агент"
    description = "Свободные деньги, резерв, достаточность поступлений"
    permissions: list[str] = []
    reads = ["остатки денег", "резерв", "прогноз поступлений", "расходы"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        from app.routers.admin_finance import position
        pos = position(db)
        out = [Finding("info", w, link="/finance") for w in pos["warnings"]]
        free = pos["free_cash_kopecks"]
        if free is not None and free < 0:
            out.append(Finding("critical", f"Свободных денег нет: не хватает {rub(-free)} до резерва",
                               "Новые закупки сейчас создадут риск для обязательств", "/finance",
                               suggestion="Отложить закупки или пересмотреть резерв"))
        elif free is not None:
            out.append(Finding("info", f"Свободно для закупок: {rub(free)}", "Остаток минус резерв", "/finance"))
        next_month = pos["forecast"][1]["expected_kopecks"] if len(pos["forecast"]) > 1 else 0
        if pos["monthly_opex_kopecks"] and next_month < pos["monthly_opex_kopecks"]:
            out.append(Finding("warning", "Ожидаемые поступления следующего месяца меньше средних расходов",
                               f"Прогноз {rub(next_month)} при расходах {rub(pos['monthly_opex_kopecks'])}",
                               "/finance"))
        return out


class CarsAgent(Agent):
    code = "cars"
    title = "Агент автомобилей"
    description = "Карточки, VIN, документы и проверочный лист перед покупкой"
    permissions = ["create:tasks"]
    reads = ["реестр автомобилей", "проверки автомобилей"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        out: list[Finding] = []
        vat_payer = get_company(db).vat_payer
        for car in db.scalars(select(Car).where(Car.status.notin_([CarStatus.sold, CarStatus.archived]))):
            title = f"{car.make} {car.model}, {car.year}"
            link = f"/cars/{car.id}"
            s = car_checks.summary(db, car)
            if s["state"] == "problem":
                out.append(Finding("critical", f"{title}: проблемы по проверке перед покупкой", s["verdict"], link))
            elif s["state"] == "incomplete":
                out.append(Finding("warning", f"{title}: проверка перед покупкой не завершена", s["verdict"], link,
                                   suggestion="Внести результаты по законным источникам с подтверждением"))
                ctx.create_task("car_check", f"Завершить проверку автомобиля: {title}", s["verdict"], link,
                                f"car_check:{car.id}", due=ctx.today + timedelta(days=2))
            if car.ownership_status == OwnershipStatus.owned and (not car.vin or not car.purchase_document.strip()):
                out.append(Finding("warning", f"{title}: в собственности, но нет VIN или документа о покупке",
                                   link=link))
            if car.is_published and not car.photos:
                out.append(Finding("info", f"{title}: опубликован без фотографий", link=link))
            long_purchase = ctx.now - aware(car.created_at) > timedelta(days=30)
            if car.ownership_status == OwnershipStatus.purchasing and long_purchase:
                out.append(Finding("info", f"{title}: в статусе «в процессе закупки» больше 30 дней", link=link))
            if vat_payer and car.ownership_status == OwnershipStatus.owned and car.purchased_from == "unknown":
                out.append(Finding("warning", f"{title}: не указано, у кого куплен автомобиль",
                                   "Влияет на порядок НДС при продаже", link, refs=["acc.nk.154_5_1"]))
        return out


class ApplicationsAgent(Agent):
    code = "applications"
    title = "Агент заявок"
    description = "Скорость обработки заявок, дубли, подбор автомобилей под заказ"
    permissions = ["create:tasks"]
    reads = ["заявки", "каталог"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        out: list[Finding] = []
        open_statuses = [ApplicationStatus.new, ApplicationStatus.in_progress, ApplicationStatus.info_requested,
                         ApplicationStatus.offer_made]
        for a in db.scalars(select(Application).where(Application.status == ApplicationStatus.new,
                                                      Application.created_at < ctx.now - timedelta(hours=24))):
            out.append(Finding("warning", f"Заявка без ответа больше суток: {a.name}", link=f"/applications/{a.id}"))
            ctx.create_task("application", f"Обработать заявку: {a.name}", "Заявка ждёт ответа больше суток",
                            f"/applications/{a.id}", f"application:{a.id}", due=ctx.today)
        phones = db.execute(select(Application.phone, func.count()).where(Application.status.in_(open_statuses))
                            .group_by(Application.phone).having(func.count() > 1)).all()
        for phone, n in phones:
            out.append(Finding("info", f"Несколько открытых заявок с одного номера ({n})", phone[-4:], "/applications"))
        cars = db.scalars(select(Car).where(Car.is_published.is_(True),
                                            Car.status.in_([CarStatus.available, CarStatus.reserved]))).all()
        for a in db.scalars(select(Application).where(Application.kind == ApplicationKind.custom_order,
                                                      Application.status.in_(open_statuses))):
            match = [c for c in cars if c.make.lower() == a.wanted_make.lower()
                     and (not a.wanted_model or a.wanted_model.lower() in c.model.lower())
                     and (not a.max_budget_kopecks or c.sale_price_kopecks <= a.max_budget_kopecks)]
            if match:
                out.append(Finding("info", f"Под заказ «{a.wanted_make} {a.wanted_model}» есть автомобиль в каталоге",
                                   ", ".join(f"{c.make} {c.model} {c.year} — {rub(c.sale_price_kopecks)}"
                                             for c in match[:3]),
                                   f"/applications/{a.id}", suggestion="Предложить клиенту"))
        return out


class ManagementAgent(Agent):
    code = "management"
    title = "Управленческий агент"
    description = "Ежедневная сводка владельцу по деньгам, долгам, задачам и выводам агентов"
    permissions = ["create:staff_notifications"]
    reads = ["показатели", "задачи", "результаты агентов"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        ledgers = live_ledgers(db, ctx.today)
        active = sum(1 for c, _ in ledgers if c.status == ContractStatus.signed)
        receivables = sum(lg.outstanding_kopecks for c, lg in ledgers if c.status == ContractStatus.signed)
        overdue = sum(lg.overdue_kopecks for _, lg in ledgers)
        week = sum(p.amount_kopecks for p in db.scalars(select(Payment).where(
            Payment.status == PaymentStatus.confirmed, Payment.received_on >= ctx.today - timedelta(days=7))))
        tasks = db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.status == TaskStatus.open)) or 0
        counts = {"critical": 0, "warning": 0}
        for code in AGENTS:
            if code == self.code:
                continue
            last = db.scalar(select(AgentRun).where(AgentRun.agent_code == code, AgentRun.status == "ok")
                             .order_by(AgentRun.started_at.desc()).limit(1))
            for f in (last.findings if last else []):
                if f["severity"] in counts:
                    counts[f["severity"]] += 1
        body = (f"Действующих договоров: {active}. Остаток долга: {rub(receivables)}, "
                f"из него просрочено {rub(overdue)}. "
                f"Поступило за 7 дней: {rub(week)}. Открытых задач: {tasks}. Выводы агентов: критичных "
                f"{counts['critical']}, предупреждений {counts['warning']}.")
        ctx.notify_staff("daily_summary", f"Сводка на {ctx.today:%d.%m.%Y}", body, "/agents")
        severity = "critical" if counts["critical"] else "warning" if overdue else "info"
        return [Finding(severity, f"Сводка на {ctx.today:%d.%m.%Y}", body, "/agents")]


class DocumentsAgent(Agent):
    code = "documents"
    title = "Агент документов"
    description = "Актуальность проектов, комплектность по договорам, целостность подписанных документов и сканов"
    permissions = ["create:tasks"]
    reads = ["документы", "договоры", "шаблоны", "сканы подписанных экземпляров"]

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        report = audit_documents(db, ctx.today)
        out: list[Finding] = []
        for issue in report["issues"]:
            link = (f"/documents/{issue['document_id']}" if issue["document_id"]
                    else f"/contracts/{issue['contract_id']}" if issue["contract_id"] else "/documents")
            if issue["severity"] == "info":
                continue
            out.append(Finding(issue["severity"], issue["title"], issue["message"], link, suggestion=issue["action"]))
            if issue["severity"] == "critical":
                ctx.create_task("document", issue["title"], f"{issue['message']} {issue['action']}", link,
                                f"document:{issue['code']}:{issue['document_id'] or issue['contract_id']}",
                                due=ctx.today)
        info = report["counts"]["info"]
        if info:
            out.append(Finding("info", f"Замечаний для сведения: {info}", "Например, не загружены сканы.",
                               "/documents"))
        return out


AGENTS: dict[str, Agent] = {a.code: a for a in (
    PaymentsAgent(), NotificationsAgent(), LegalAgent(), DocumentsAgent(), AccountingAgent(), FinanceAgent(),
    CarsAgent(), ApplicationsAgent(), ManagementAgent())}
