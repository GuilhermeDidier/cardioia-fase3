"""Formatação de horário no fuso de Brasília (mesmo critério do dashboard)."""

from datetime import datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, FUSO).isoformat(timespec="milliseconds")


def hora(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, FUSO).strftime("%H:%M:%S")
