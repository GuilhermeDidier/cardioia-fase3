"""API REST do CardioIA: recebe leituras do ESP32, avalia o risco e avisa a equipe.

Uso (a partir da raiz do repositório, com api/.env preenchido):
  uvicorn api.app.main:criar_app --factory --port 8000
  Documentação interativa: http://localhost:8000/docs
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query

from .auth import exigir_papel
from .config import RAIZ_REPO, Config
from .modelos import LeituraCriada, LeituraEntrada, RiscoSaida, StatusEntrada
from .notificador import Notificador
from .repositorio import Repositorio
from .risco import classificar
from .tempo import iso

log = logging.getLogger("cardioia.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

Paciente = Annotated[str, Path(pattern=r"^P\d{3}$", description="Pseudônimo do paciente, ex.: P001")]
INTERVALO_SILENCIO_S = 10


def _leitura_saida(l: dict) -> dict:
    return {
        "id": l["id"], "seq": l["seq"], "recebida_em": iso(l["recebida_em"]), "medida_em": iso(l["medida_em"]),
        "temp": l["temp"], "umid": l["umid"], "bpm": l["bpm"], "origem": l["origem"],
        "alerta": bool(l["alerta"]), "motivo": l["motivo"], "nivel": l["nivel"],
        "divergencia_esp32": bool(l["divergencia"]),
    }


def criar_app(config: Config | None = None) -> FastAPI:
    config = config or Config.do_ambiente()
    repo = Repositorio(config.banco)
    repo.criar_tabelas()
    notificador = Notificador(config, repo)

    async def vigiar_silencio():
        while True:
            await asyncio.sleep(INTERVALO_SILENCIO_S)
            await asyncio.to_thread(notificador.verificar_silencio, time.time())

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        tarefa = asyncio.create_task(vigiar_silencio()) if config.verificar_silencio_em_loop else None
        log.info("[API] pronta | banco=%s | smtp=%s:%s", os.path.relpath(config.banco, RAIZ_REPO),
                 config.smtp_host, config.smtp_port)
        yield
        if tarefa:
            tarefa.cancel()

    app = FastAPI(
        title="CardioIA — API de monitoramento",
        version="1.0.0",
        description="Recebe as leituras do wearable (ESP32), verifica o risco e avisa a equipe por e-mail. "
                    "Rotas de envio exigem a chave do papel *dispositivo*; rotas de consulta, a do papel *equipe*.",
        lifespan=ciclo_de_vida,
    )
    app.state.config = config
    app.state.notificador = notificador
    dispositivo = Depends(exigir_papel("dispositivo"))
    equipe = Depends(exigir_papel("equipe"))

    @app.get("/saude", tags=["infra"])
    def saude():
        return {"status": "ok", "versao": app.version, "smtp": f"{config.smtp_host}:{config.smtp_port}"}

    @app.post("/pacientes/{paciente}/leituras", status_code=201, response_model=LeituraCriada,
              tags=["dispositivo"], dependencies=[dispositivo])
    def receber_leitura(corpo: LeituraEntrada, paciente: Paciente):
        if corpo.paciente is not None and corpo.paciente != paciente:
            raise HTTPException(422, f"O corpo é do paciente {corpo.paciente}, mas a rota é de {paciente}")
        recebida = time.time()
        medida = recebida - corpo.idade_ms / 1000
        risco = classificar(corpo.bpm, corpo.temp)
        divergencia = risco.alerta != corpo.alerta
        if divergencia:
            log.warning("[RISCO] divergência na seq %s de %s: esp32=%s api=%s", corpo.seq, paciente,
                        corpo.alerta, risco.alerta)
        leitura = dict(paciente=paciente, seq=corpo.seq, recebida_em=recebida, medida_em=medida, temp=corpo.temp,
                       umid=corpo.umid, bpm=corpo.bpm, origem=corpo.origem, alerta_esp32=int(corpo.alerta),
                       alerta=int(risco.alerta), motivo=risco.motivo, nivel=risco.nivel, divergencia=int(divergencia))
        id_leitura = repo.inserir_leitura(**leitura)
        notificador.conhecer(paciente)
        email = notificador.processar(paciente, {**leitura, "buffer_pendente": corpo.buffer_pendente}, risco)
        log.info("[LEITURA] %s seq=%s bpm=%s temp=%s origem=%s risco=%s", paciente, corpo.seq, corpo.bpm,
                 corpo.temp, corpo.origem, risco.motivo or "normal")
        return LeituraCriada(
            id=id_leitura or 0, recebida_em=iso(recebida), medida_em=iso(medida),
            risco=RiscoSaida(alerta=risco.alerta, motivos=list(risco.motivos), nivel=risco.nivel),
            divergencia_esp32=divergencia, email_enviado=email,
        )

    @app.post("/pacientes/{paciente}/status", status_code=201, tags=["dispositivo"], dependencies=[dispositivo])
    def receber_status(corpo: StatusEntrada, paciente: Paciente):
        repo.salvar_status(paciente, time.time(), corpo.model_dump(exclude_none=True))
        return {"ok": True}

    @app.get("/pacientes/{paciente}/leituras", tags=["equipe"], dependencies=[equipe])
    def listar_leituras(paciente: Paciente, limite: int = Query(50, ge=1, le=1000)):
        return [_leitura_saida(l) for l in repo.listar_leituras(paciente, limite)]

    @app.get("/pacientes/{paciente}/alertas", tags=["equipe"], dependencies=[equipe])
    def listar_alertas(paciente: Paciente, limite: int = Query(50, ge=1, le=1000)):
        return [_leitura_saida(l) for l in repo.listar_leituras(paciente, limite, so_alertas=True)]

    @app.get("/pacientes/{paciente}/resumo", tags=["equipe"], dependencies=[equipe])
    def resumo(paciente: Paciente):
        ultima = repo.ultima_leitura(paciente)
        if ultima is None:
            raise HTTPException(404, f"Nenhuma leitura de {paciente}")
        agora = time.time()
        status = repo.ultimo_status(paciente)
        if status:
            status["recebido_em"] = iso(status["recebido_em"])
        emails = [e for e in repo.listar_emails(1000) if e["paciente"] == paciente]
        return {
            "paciente": paciente,
            "ultima_leitura": _leitura_saida(ultima),
            "estado": ultima["motivo"] or "normal",
            "segundos_sem_dados": round(agora - (repo.ultima_chegada(paciente) or agora), 1),
            "alertas_24h": repo.contar_alertas_desde(paciente, agora - 86400),
            "dispositivo": status,
            "emails": {"enviados": sum(e["status"] == "enviado" for e in emails),
                       "falharam": sum(e["status"] == "falhou" for e in emails)},
        }

    @app.get("/emails", tags=["equipe"], dependencies=[equipe])
    def listar_emails(limite: int = Query(100, ge=1, le=1000)):
        return [{**e, "criado_em": iso(e["criado_em"])} for e in repo.listar_emails(limite)]

    return app
