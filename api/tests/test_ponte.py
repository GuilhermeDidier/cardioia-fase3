"""A ponte repassa o log real da rodada no Wokwi (docs/evidencias/broker_mqtt.log) para a API."""

from api.app.config import RAIZ_REPO
from api.cliente.cliente_rest import ClienteCardioIA
from api.cliente.ponte_mqtt import replay

from .conftest import CHAVE_DISPOSITIVO, CHAVE_EQUIPE

LOG = RAIZ_REPO / "docs" / "evidencias" / "broker_mqtt.log"


def test_replay_do_log_real(api, caixa):
    linhas = LOG.read_text(encoding="utf-8").splitlines()
    esperadas = sum("/leituras " in l for l in linhas)
    duplicadas = sum("/alertas " in l for l in linhas)

    contagem = replay(str(LOG), ClienteCardioIA(chave=CHAVE_DISPOSITIVO, http=api))

    assert contagem["leitura"] == esperadas
    assert contagem["alerta_duplicado"] == duplicadas
    assert contagem["recusada"] == 0 and contagem["invalida"] == 0
    gravadas = api.get("/pacientes/P001/leituras", params={"limite": 1000}, headers={"X-API-Key": CHAVE_EQUIPE}).json()
    assert len(gravadas) == esperadas
    assert len(caixa.mensagens) >= 1
