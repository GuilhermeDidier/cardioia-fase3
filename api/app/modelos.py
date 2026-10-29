"""Formatos de entrada e saída da API.

LeituraEntrada espelha o JSON que o firmware publica no MQTT (função enviar()
do cardioia_monitor.ino), para que a ponte repasse a mensagem sem traduzir.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LeituraEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paciente: str | None = None
    seq: int = Field(ge=1)
    idade_ms: int = Field(ge=0)
    temp: float | None = Field(default=None, ge=-10, le=60)
    umid: int | None = Field(default=None, ge=0, le=100)
    bpm: int = Field(ge=0, le=300)
    alerta: bool
    motivo: str = ""
    origem: Literal["tempo_real", "buffer"]
    buffer_pendente: int = Field(ge=0)


class StatusEntrada(BaseModel):
    # O Last Will traz só {"online": false, "motivo": "lwt"}; o resto é opcional
    online: bool
    motivo: str | None = None
    buffer: int | None = Field(default=None, ge=0)
    capacidade: int | None = Field(default=None, ge=0)
    descartadas_normais: int | None = Field(default=None, ge=0)
    descartadas_alertas: int | None = Field(default=None, ge=0)
    sincronizadas: int | None = Field(default=None, ge=0)
    erros_sensor: int | None = Field(default=None, ge=0)
    uptime_s: int | None = Field(default=None, ge=0)


class RiscoSaida(BaseModel):
    alerta: bool
    motivos: list[str]
    nivel: str


class LeituraCriada(BaseModel):
    id: int
    recebida_em: str
    medida_em: str
    risco: RiscoSaida
    divergencia_esp32: bool
    email_enviado: bool
