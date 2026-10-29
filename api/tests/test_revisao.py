"""Casos achados na revisão de código (cada um falhava antes da correção)."""

import time
from collections import Counter
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.app.config import RAIZ_REPO
from api.app.main import criar_app
from api.cliente.cliente_rest import ClienteCardioIA
from api.cliente.ponte_mqtt import replay, tratar_mensagem

from .conftest import CHAVE_DISPOSITIVO, CHAVE_EQUIPE, enviar, leitura

EQUIPE = {"X-API-Key": CHAVE_EQUIPE}


def test_idade_absurda_e_rejeitada_e_nao_quebra_as_consultas(api):
    assert enviar(api, leitura(idade_ms=10**20)).status_code == 422
    assert api.get("/pacientes/P001/leituras", headers=EQUIPE).status_code == 200


def test_chave_com_caractere_fora_do_ascii_da_401_e_nao_500(api):
    assert api.get("/emails", headers={"X-API-Key": b"\xe9abc"}).status_code == 401


def test_normalizar_durante_a_queda_gera_email(api, caixa):
    enviar(api, leitura(seq=1, bpm=140))                        # alerta em tempo real
    enviar(api, leitura(seq=2, bpm=80, origem="buffer", pendente=1, idade_ms=4000))
    enviar(api, leitura(seq=3, bpm=80, origem="buffer", pendente=0, idade_ms=2000))
    assuntos = caixa.assuntos()
    assert len(assuntos) == 2 and assuntos[1].startswith("Normalizado (durante a queda de conexão)")


def test_envio_smtp_acontece_fora_da_trava(api, monkeypatch):
    notificador = api.app.state.notificador
    trava_presa = []
    original = notificador._enviar
    monkeypatch.setattr(notificador, "_enviar", lambda *a: trava_presa.append(notificador._trava.locked()) or original(*a))
    enviar(api, leitura(bpm=140))
    assert trava_presa == [False]


def test_apos_reiniciar_a_api_continua_vigiando_o_silencio(config, caixa):
    with TestClient(criar_app(config)) as api:
        enviar(api, leitura(seq=1))
    with TestClient(criar_app(config)) as api:                 # mesma base, processo novo
        assert api.app.state.notificador.verificar_silencio(time.time() + 61) == ["P001"]


def test_ponte_sobrevive_a_api_fora_do_ar():
    cliente = ClienteCardioIA("http://127.0.0.1:1", CHAVE_DISPOSITIVO)
    contagem = replay(str(RAIZ_REPO / "docs" / "evidencias" / "broker_mqtt.log"), cliente)
    assert contagem["sem_api"] > 0 and contagem["leitura"] == 0


def test_ponte_ignora_mensagem_retida(api):
    contagem: Counter = Counter()
    status = SimpleNamespace(topic="cardioia/fase3/g568457/paciente/P001/status", retain=True,
                             payload=b'{"online": false, "motivo": "lwt"}')
    tratar_mensagem(status, ClienteCardioIA(chave=CHAVE_DISPOSITIVO, http=api), contagem)
    assert contagem == Counter(retida=1)
