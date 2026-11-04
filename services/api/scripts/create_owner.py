"""Создание первой учётной записи владельца.

Пароль запрашивается интерактивно и нигде не сохраняется в открытом виде:
    python -m scripts.create_owner --login owner@example.ru --name "Фамилия Имя"

Для автоматизации (например, локального стенда) пароль можно передать через переменную окружения:
    python -m scripts.create_owner --login ... --name ... --password-env OWNER_PASSWORD
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Role, User
from app.security import MIN_PASSWORD_LENGTH, hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Создать владельца Islamic Car")
    parser.add_argument("--login", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password-env", help="Имя переменной окружения с паролем (без интерактивного ввода)")
    args = parser.parse_args()

    if args.password_env:
        password = os.environ.get(args.password_env, "")
    else:
        password = getpass.getpass("Пароль владельца: ")
        if password != getpass.getpass("Повторите пароль: "):
            print("Пароли не совпадают", file=sys.stderr)
            return 1
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        login = args.login.strip().lower()
        if db.scalar(select(User).where(User.login == login)):
            print("Пользователь с таким логином уже существует", file=sys.stderr)
            return 1
        db.add(User(login=login, full_name=args.name, role=Role.owner, password_hash=hash_password(password)))
        db.commit()
    print(f"Владелец {login} создан. После входа включите второй фактор в разделе «Настройки».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
