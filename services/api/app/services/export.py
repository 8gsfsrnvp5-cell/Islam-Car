"""CSV-выгрузки, которые корректно открываются в русском Excel."""

import csv
import io

from fastapi.responses import Response


def csv_response(rows: list[list[str]], filename: str) -> Response:
    buf = io.StringIO()
    csv.writer(buf, delimiter=";").writerows(rows)
    # BOM — чтобы Excel определил кодировку UTF-8
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def money(kopecks: int) -> str:
    rubles, kop = divmod(kopecks, 100)
    return f"{rubles},{kop:02d}"
