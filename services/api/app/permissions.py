"""Карта прав сотрудников. Проверяется только на сервере."""

from app.models import Role

OWN, ADM, MGR, ACC = Role.owner, Role.admin, Role.manager, Role.accountant
LAW, SHA, AUD = Role.lawyer, Role.shariah_advisor, Role.auditor
ALL_STAFF = {OWN, ADM, MGR, ACC, LAW, SHA, AUD}
FINANCE_VIEW = {OWN, ADM, ACC, AUD}

PERMISSIONS: dict[str, set[Role]] = {
    "dashboard.read": ALL_STAFF,
    "finance.read": FINANCE_VIEW,  # себестоимость, наценка, расходы, результат
    "cars.read": ALL_STAFF,
    "cars.write": {OWN, ADM, MGR},
    "cars.cost": FINANCE_VIEW | {SHA},  # закупочная стоимость: коммерческая тайна; для мурабахи её видит специалист
    "applications.read": {OWN, ADM, MGR, AUD},
    "applications.write": {OWN, ADM, MGR},
    "clients.read": ALL_STAFF,
    "clients.write": {OWN, ADM, MGR},
    "clients.pd": {OWN, ADM, MGR, LAW},  # паспортные данные и контакты без маскирования
    "clients.verify": {OWN, ADM},
    "clients.access": {OWN, ADM},  # выдача доступа в личный кабинет
    "contracts.read": ALL_STAFF,
    "contracts.write": {OWN, ADM, MGR},
    "contracts.sign": {OWN, ADM},
    "payments.read": ALL_STAFF - {SHA},
    "payments.confirm": {OWN, ADM, ACC},
    "payments.import": {OWN, ADM, ACC},  # загрузка банковских выписок
    "payments.reverse": {OWN, ADM},
    "expenses.write": {OWN, ADM, ACC},
    "support.read": {OWN, ADM, MGR},
    "support.write": {OWN, ADM, MGR},
    "notifications.read": ALL_STAFF,
    "reports.read": FINANCE_VIEW,
    "audit.read": {OWN, ADM, AUD},
    "documents.content": {OWN, ADM},  # Полные документы содержат одновременно ПД и закупочную стоимость.
    "documents.audit": {OWN, ADM, MGR, LAW, AUD},  # проверка комплектности и актуальности документов
    "templates.approve": {OWN, LAW},  # фиксирует утверждение шаблона юристом
    "knowledge.read": ALL_STAFF,
    # Заключение по записи библиотеки фиксирует профильный специалист (или владелец со слов специалиста)
    "knowledge.review": {OWN, LAW, ACC, SHA},
    "knowledge.review.legal": {OWN, LAW},
    "knowledge.review.accounting": {OWN, ACC},
    "knowledge.review.islamic-finance": {OWN, SHA},
    "accounting.read": FINANCE_VIEW,
    "accounting.write": {OWN, ACC},       # вносит параметры правил и события налогового календаря
    "accounting.approve": {OWN},          # утверждает параметры налоговых правил
    "agents.read": ALL_STAFF,
    "agents.run": {OWN, ADM},
    "assistant.use": {OWN, ADM, MGR, ACC, LAW, SHA},  # помощник по библиотекам знаний (без персональных данных)
    "settings.write": {OWN},
    "users.manage": {OWN},
}


def has_permission(role: Role, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


def permissions_for(role: Role) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)
