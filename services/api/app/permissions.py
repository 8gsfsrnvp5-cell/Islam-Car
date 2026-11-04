"""Карта прав сотрудников. Проверяется только на сервере."""

from app.models import Role

OWN, ADM, MGR, ACC = Role.owner, Role.admin, Role.manager, Role.accountant
ALL_STAFF = {OWN, ADM, MGR, ACC}

PERMISSIONS: dict[str, set[Role]] = {
    "dashboard.read": ALL_STAFF,
    "finance.read": {OWN, ADM, ACC},  # себестоимость, наценка, расходы, результат
    "cars.read": ALL_STAFF,
    "cars.write": {OWN, ADM, MGR},
    "cars.cost": {OWN, ADM, ACC},  # закупочная стоимость — коммерческая тайна
    "applications.read": {OWN, ADM, MGR},
    "applications.write": {OWN, ADM, MGR},
    "clients.read": ALL_STAFF,
    "clients.write": {OWN, ADM, MGR},
    "clients.pd": {OWN, ADM, MGR},  # паспортные данные без маскирования
    "clients.verify": {OWN, ADM},
    "clients.access": {OWN, ADM},  # выдача доступа в личный кабинет
    "contracts.read": ALL_STAFF,
    "contracts.write": {OWN, ADM, MGR},
    "contracts.sign": {OWN, ADM},
    "payments.read": ALL_STAFF,
    "payments.confirm": {OWN, ADM, ACC},
    "payments.reverse": {OWN, ADM},
    "expenses.write": {OWN, ADM, ACC},
    "support.read": {OWN, ADM, MGR},
    "support.write": {OWN, ADM, MGR},
    "notifications.read": ALL_STAFF,
    "reports.read": {OWN, ADM, ACC},
    "audit.read": {OWN, ADM},
    "knowledge.read": ALL_STAFF,
    "knowledge.review": {OWN},           # фиксирует заключение юриста, бухгалтера или специалиста по шариату
    "accounting.read": {OWN, ADM, ACC},
    "accounting.write": {OWN, ACC},       # вносит параметры правил и события налогового календаря
    "accounting.approve": {OWN},          # утверждает параметры налоговых правил
    "agents.read": ALL_STAFF,
    "agents.run": {OWN, ADM},
    "settings.write": {OWN},
    "users.manage": {OWN},
}


def has_permission(role: Role, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


def permissions_for(role: Role) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)
