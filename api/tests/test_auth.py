"""Rotas de escrita e de consulta exigem a chave do papel certo."""

from .conftest import CHAVE_DISPOSITIVO, CHAVE_EQUIPE, enviar, leitura


def test_post_sem_chave_e_recusado(api):
    resposta = api.post("/pacientes/P001/leituras", json=leitura())
    assert resposta.status_code == 401
    assert api.get("/pacientes/P001/leituras", headers={"X-API-Key": CHAVE_EQUIPE}).json() == []


def test_post_com_chave_invalida_e_recusado(api):
    assert enviar(api, leitura(), chave="chave-errada").status_code == 401


def test_post_com_chave_da_equipe_e_proibido(api):
    assert enviar(api, leitura(), chave=CHAVE_EQUIPE).status_code == 403


def test_status_sem_chave_e_recusado(api):
    assert api.post("/pacientes/P001/status", json={"online": True}).status_code == 401


def test_consulta_exige_chave_da_equipe(api):
    assert api.get("/pacientes/P001/leituras").status_code == 401
    assert api.get("/emails").status_code == 401
    assert api.get("/pacientes/P001/leituras", headers={"X-API-Key": CHAVE_DISPOSITIVO}).status_code == 403


def test_dispositivo_envia_e_equipe_consulta(api):
    assert enviar(api, leitura()).status_code == 201
    resposta = api.get("/pacientes/P001/leituras", headers={"X-API-Key": CHAVE_EQUIPE})
    assert resposta.status_code == 200 and len(resposta.json()) == 1


def test_saude_e_publica(api):
    assert api.get("/saude").status_code == 200
