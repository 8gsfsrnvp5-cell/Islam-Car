"""Запуск: python -m app.worker  (или --once для одного прохода, например из планировщика задач)."""

import sys

from app.worker.runner import run_forever, run_once

if __name__ == "__main__":
    if "--once" in sys.argv:
        print(f"Выполнено задач: {run_once()}")
    else:
        run_forever()
