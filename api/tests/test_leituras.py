"""Validação de entrada, horário da medida e consulta."""

from datetime import datetime

from .conftest import CHAVE_EQUIPE, enviar, leitura

EQUIPE = {"X-API-Key": CHAVE_EQUIPE}


def test_bpm_fora_da_faixa_e_rejeitado(api):
    assert enviar(api, leitura(bpm=400)).status_code == 422


def test_paciente_invalido_na_rota_e_rejeitado(api):
    assert enviar(api, leitura(), paciente="X").status_code == 422


def test_paciente_do_corpo_diferente_da_rota_e_rejeitado(api):
    assert enviar(api, leitura(), paciente="P002").status_code == 422


def test_idade_negativa_e_campo_extra_sao_rejeitados(api):
    assert enviar(api, leitura(idade_ms=-1)).status_code == 422
    assert enviar(api, leitura(campo_estranho=1)).status_code == 422


def test_medida_em_desconta_a_idade(api):
    corpo = enviar(api, leitura(idade_ms=60_000)).json()
    diferenca = datetime.fromisoformat(corpo["recebida_em"]) - datetime.fromisoformat(corpo["medida_em"])
    assert abs(diferenca.total_seconds() - 60) < 0.01


def test_leituras_saem_ordenadas_pela_medida_mesmo_chegando_fora_de_ordem(api):
    enviar(api, leitura(seq=10, idade_ms=0))
    enviar(api, leitura(seq=3, idade_ms=30_000, origem="buffer", pendente=0))   # chega depois, mediu antes
    seqs = [l["seq"] for l in api.get("/pacientes/P001/leituras", headers=EQUIPE).json()]
    assert seqs == [3, 10]


def test_divergencia_com_o_esp32_e_sinalizada(api):
    corpo = enviar(api, leitura(bpm=130, alerta=False)).json()
    assert corpo["risco"]["alerta"] is True and corpo["divergencia_esp32"] is True


def test_resumo_e_alertas(api):
    enviar(api, leitura(seq=1))
    enviar(api, leitura(seq=2, bpm=130))
    api.post("/pacientes/P001/status", json={"online": True, "buffer": 0, "sincronizadas": 3},
             headers={"X-API-Key": "teste-dispositivo"})
    resumo = api.get("/pacientes/P001/resumo", headers=EQUIPE).json()
    assert resumo["estado"] == "taquicardia"
    assert resumo["alertas_24h"] == {"taquicardia": 1}
    assert resumo["dispositivo"]["sincronizadas"] == 3
    assert [a["seq"] for a in api.get("/pacientes/P001/alertas", headers=EQUIPE).json()] == [2]


def test_resumo_de_paciente_sem_dados_e_404(api):
    assert api.get("/pacientes/P009/resumo", headers=EQUIPE).status_code == 404
