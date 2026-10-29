"""E-mails de verdade (servidor SMTP aiosmtpd local): quando saem e quando não saem."""

import time

from fastapi.testclient import TestClient

from api.app.config import Config
from api.app.main import criar_app

from .conftest import CHAVE_EQUIPE, enviar, leitura


def test_leitura_normal_nao_gera_email(api, caixa):
    enviar(api, leitura())
    assert caixa.mensagens == []


def test_transicoes_geram_um_email_cada(api, caixa):
    enviar(api, leitura(seq=1))
    assert enviar(api, leitura(seq=2, bpm=135)).json()["email_enviado"] is True
    enviar(api, leitura(seq=3, bpm=140))                       # continua em alerta: não repete
    enviar(api, leitura(seq=4, bpm=80))                        # normalizou
    assuntos = caixa.assuntos()
    assert len(assuntos) == 2
    assert "ALERTA taquicardia" in assuntos[0] and "P001" in assuntos[0] and "135 bpm" in assuntos[0]
    assert assuntos[1].startswith("Normalizado")


def test_alerta_critico_tem_prefixo(api, caixa):
    enviar(api, leitura(bpm=160))
    assert caixa.assuntos()[0].startswith("[CRÍTICO]")


def test_alertas_do_buffer_viram_um_unico_resumo(api, caixa):
    for i, pendente in enumerate([3, 2, 1, 0]):
        enviar(api, leitura(seq=10 + i, bpm=170, origem="buffer", pendente=pendente, idade_ms=(4 - i) * 2000))
    assuntos = caixa.assuntos()
    assert len(assuntos) == 1
    assert assuntos[0].startswith("Sincronização: 4 leitura(s)") and "taquicardia ×4" in assuntos[0]
    # a primeira leitura em tempo real ainda em taquicardia não reanuncia o alerta
    enviar(api, leitura(seq=20, bpm=170))
    assert len(caixa.mensagens) == 1


def test_sincronizacao_interrompida_avisa_na_primeira_leitura_em_tempo_real(api, caixa):
    enviar(api, leitura(seq=1, bpm=170, origem="buffer", pendente=5, idade_ms=4000))
    enviar(api, leitura(seq=2, bpm=80))
    assert caixa.assuntos()[0].startswith("Sincronização incompleta: 1 leitura(s)")


def test_silencio_avisa_uma_vez_por_episodio(config, caixa):
    with TestClient(criar_app(config)) as api:
        enviar(api, leitura(seq=1))
        agora = time.time()
        # em produção quem chama é a tarefa de fundo a cada 10 s; aqui o relógio é injetado
        notificador = api.app.state.notificador
        assert notificador.verificar_silencio(agora + 30) == []
        assert notificador.verificar_silencio(agora + 61) == ["P001"]
        assert notificador.verificar_silencio(agora + 120) == []
        assert caixa.assuntos()[0].startswith("Sem dados do paciente P001")
        enviar(api, leitura(seq=2))                            # dado novo encerra o episódio
        assert notificador.verificar_silencio(time.time() + 61) == ["P001"]


def test_smtp_fora_do_ar_nao_derruba_a_api(tmp_path):
    config = Config(chave_dispositivo="d", chave_equipe="e", banco=str(tmp_path / "x.db"),
                    smtp_host="127.0.0.1", smtp_port=1, verificar_silencio_em_loop=False)
    with TestClient(criar_app(config)) as api:
        resposta = api.post("/pacientes/P001/leituras", json=leitura(bpm=150), headers={"X-API-Key": "d"})
        assert resposta.status_code == 201 and resposta.json()["email_enviado"] is False
        emails = api.get("/emails", headers={"X-API-Key": "e"}).json()
        assert emails[0]["status"] == "falhou" and emails[0]["erro"]

