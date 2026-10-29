"""Fixtures: API com banco temporário e um servidor SMTP de verdade (aiosmtpd) que guarda os e-mails."""

import socket

import pytest
from aiosmtpd.controller import Controller
from fastapi.testclient import TestClient

from api.app.config import Config
from api.app.main import criar_app

CHAVE_DISPOSITIVO = "teste-dispositivo"
CHAVE_EQUIPE = "teste-equipe"


class CaixaDeEntrada:
    def __init__(self):
        self.mensagens = []

    async def handle_DATA(self, server, session, envelope):
        self.mensagens.append(envelope.content.decode("utf-8", errors="replace"))
        return "250 OK"

    def assuntos(self):
        from email import message_from_string
        from email.header import decode_header, make_header
        return [str(make_header(decode_header(message_from_string(m)["Subject"]))) for m in self.mensagens]


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def smtp():
    caixa = CaixaDeEntrada()
    controlador = Controller(caixa, hostname="127.0.0.1", port=porta_livre())
    controlador.start()
    yield controlador.port, caixa
    controlador.stop()


@pytest.fixture
def config(tmp_path, smtp):
    porta, _ = smtp
    return Config(chave_dispositivo=CHAVE_DISPOSITIVO, chave_equipe=CHAVE_EQUIPE, banco=str(tmp_path / "teste.db"),
                  smtp_host="127.0.0.1", smtp_port=porta, silencio_s=60, verificar_silencio_em_loop=False)


@pytest.fixture
def api(config):
    with TestClient(criar_app(config)) as cliente:
        yield cliente


@pytest.fixture
def caixa(smtp):
    return smtp[1]


def leitura(seq=1, bpm=78, temp=36.6, origem="tempo_real", pendente=0, idade_ms=0, alerta=None, **extra):
    """Monta o JSON no formato do firmware. 'alerta' segue os limiares, salvo se informado."""
    if alerta is None:
        alerta = bpm > 120 or bpm < 50 or (temp is not None and (temp > 38 or temp < 35))
    return {"paciente": "P001", "seq": seq, "idade_ms": idade_ms, "temp": temp, "umid": 45, "bpm": bpm,
            "alerta": alerta, "motivo": "", "origem": origem, "buffer_pendente": pendente, **extra}


def enviar(api, corpo, chave=CHAVE_DISPOSITIVO, paciente="P001"):
    return api.post(f"/pacientes/{paciente}/leituras", json=corpo, headers={"X-API-Key": chave})
