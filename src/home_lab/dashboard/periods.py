"""Shared monthly dashboard period helpers."""

from __future__ import annotations

from calendar import monthrange
from datetime import date


MONTH_NAMES = (
    "",
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


def month_label(value: date) -> str:
    return f"{MONTH_NAMES[value.month]} {value.year}"


def months_between(start: date, end: date) -> list[date]:
    month = start.replace(day=1)
    last_month = end.replace(day=1)
    months = []
    while month <= last_month:
        months.append(month)
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return months


def month_bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    return start, start.replace(day=monthrange(start.year, start.month)[1])
