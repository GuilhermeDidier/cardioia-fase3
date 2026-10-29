"""Automação de e-mail para a equipe de saúde.

Regras (as mesmas do nó "quando notificar" do Node-RED, para os dois avisos
contarem a mesma história):
  1. tempo real, normal → alerta: um e-mail de ALERTA (sem repetir a cada leitura);
  2. tempo real, alerta → normal: um e-mail de normalização;
  3. leituras do buffer em alerta: acumulam e viram UM e-mail de resumo no fim da
     sincronização (buffer_pendente = 0) ou na primeira leitura em tempo real;
  4. silêncio: sem leitura há mais de SILENCIO_S segundos, um e-mail por episódio.

O envio usa SMTP de verdade (Mailpit em Docker, que nunca repassa para fora).
Falha de SMTP não derruba a API: fica registrada na tabela de e-mails.
"""

import logging
import smtplib
import threading
import time
from email.message import EmailMessage

from .repositorio import Repositorio
from .risco import Risco
from .tempo import hora

log = logging.getLogger("cardioia.email")
NIVEIS = {"normal": "normal", "atencao": "atenção", "critico": "crítico"}
Email = tuple[str, str, str, str]   # paciente, tipo, assunto, corpo


class Notificador:
    def __init__(self, config, repo: Repositorio):
        self.config = config
        self.repo = repo
        self._trava = threading.Lock()   # as rotas rodam em threads; o estado abaixo é compartilhado
        self._motivo_anterior: dict[str, str] = {}
        self._alertas_offline: dict[str, list[tuple[float, str]]] = {}
        self._em_silencio: set[str] = set()

    # ------------------------------------------------------------------ regras
    # A decisão (estado compartilhado) acontece sob a trava; o envio SMTP, que pode
    # demorar até o timeout, acontece depois, para não segurar as outras leituras.

    def processar(self, paciente: str, leitura: dict, risco: Risco) -> bool:
        """Aplica as regras 1–3 a uma leitura já gravada. Retorna se algum e-mail saiu."""
        with self._trava:
            emails = self._decidir(paciente, leitura, risco)
        return any([self._enviar(*e) for e in emails])

    def _decidir(self, paciente: str, leitura: dict, risco: Risco) -> list[Email]:
        self._em_silencio.discard(paciente)
        emails: list[Email] = []
        offline = self._alertas_offline.setdefault(paciente, [])
        anterior = self._motivo_anterior.get(paciente, "")

        if leitura["origem"] == "buffer":
            if risco.alerta:
                offline.append((leitura["medida_em"], risco.motivo))
            if leitura["buffer_pendente"] != 0:
                return emails
            # Fim da sincronização: a referência passa a ser a última leitura do buffer,
            # para a próxima leitura em tempo real não anunciar o que já aconteceu offline
            if offline:
                emails.append(self._email_resumo(paciente, offline, "Sincronização"))
                offline.clear()
            if anterior and not risco.alerta:   # estava em alerta e normalizou durante a queda
                emails.append(self._email_normalizado(paciente, leitura, " (durante a queda de conexão)"))
            self._motivo_anterior[paciente] = risco.motivo
            return emails

        if offline:
            emails.append(self._email_resumo(paciente, offline, "Sincronização incompleta"))
            offline.clear()
        if risco.motivo != anterior:
            self._motivo_anterior[paciente] = risco.motivo
            emails.append(self._email_alerta(paciente, leitura, risco) if risco.alerta
                          else self._email_normalizado(paciente, leitura))
        return emails

    def verificar_silencio(self, agora: float) -> list[str]:
        """Regra 4. Recebe o relógio como parâmetro para ser testável sem esperar."""
        emails: list[Email] = []
        with self._trava:
            for paciente in list(self._motivo_anterior):
                ultima = self.repo.ultima_chegada(paciente)
                if ultima is None or paciente in self._em_silencio:
                    continue
                parado = agora - ultima
                if parado > self.config.silencio_s:
                    self._em_silencio.add(paciente)
                    emails.append((
                        paciente, "silencio", f"Sem dados do paciente {paciente} há {int(parado)} s",
                        f"A última leitura de {paciente} chegou às {hora(ultima)}. Pode ser queda de conexão "
                        f"(o ESP32 guarda as leituras no buffer) ou o dispositivo desligado/fora do corpo.\n"
                        f"Verificar o paciente."))
        for e in emails:
            self._enviar(*e)
        return [e[0] for e in emails]

    def conhecer(self, *pacientes: str):
        """Passa a vigiar o silêncio dos pacientes (na 1ª leitura e, ao subir a API, os do banco)."""
        with self._trava:
            for paciente in pacientes:
                self._motivo_anterior.setdefault(paciente, "")

    # ------------------------------------------------------------------ e-mails

    def _email_alerta(self, paciente: str, leitura: dict, risco: Risco) -> Email:
        prefixo = "[CRÍTICO] " if risco.nivel == "critico" else ""
        assunto = (f"{prefixo}ALERTA {risco.motivo.replace('+', ' + ')} — {paciente} — "
                   f"{leitura['bpm']} bpm, {_temp(leitura['temp'])}")
        corpo = (f"Alerta de {risco.motivo.replace('+', ' + ')} (nível {NIVEIS[risco.nivel]}) "
                 f"no paciente {paciente} às {hora(leitura['medida_em'])}.\n\n" + self._historico(paciente))
        return paciente, "alerta", assunto, corpo

    def _email_normalizado(self, paciente: str, leitura: dict, quando: str = "") -> Email:
        assunto = f"Normalizado{quando} — {paciente} — {leitura['bpm']} bpm, {_temp(leitura['temp'])}"
        corpo = (f"O paciente {paciente} voltou à faixa normal{quando}; leitura de "
                 f"{hora(leitura['medida_em'])}.\n\n" + self._historico(paciente))
        return paciente, "normalizado", assunto, corpo

    def _email_resumo(self, paciente: str, alertas: list[tuple[float, str]], titulo: str) -> Email:
        contagem: dict[str, int] = {}
        for _, motivo in alertas:
            for m in motivo.split("+"):
                contagem[m] = contagem.get(m, 0) + 1
        tipos = ", ".join(f"{m} ×{n}" for m, n in contagem.items())
        assunto = f"{titulo}: {len(alertas)} leitura(s) em alerta durante a queda — {paciente} — {tipos}"
        linhas = "\n".join(f"  {hora(t)}  {m}" for t, m in alertas)
        corpo = (f"O dispositivo de {paciente} ficou sem conexão e guardou as leituras no buffer local.\n"
                 f"Ao sincronizar, {len(alertas)} delas estavam em alerta:\n\n{linhas}\n")
        return paciente, "sincronizacao", assunto, corpo

    def _historico(self, paciente: str) -> str:
        linhas = ["Últimas leituras:", "  hora      bpm  temp     estado"]
        for l in self.repo.listar_leituras(paciente, 6):
            estado = l["motivo"] or "normal"
            linhas.append(f"  {hora(l['medida_em'])}  {l['bpm']:>3}  {_temp(l['temp']):>7}  {estado}")
        return "\n".join(linhas) + "\n"

    def _enviar(self, paciente: str, tipo: str, assunto: str, corpo: str) -> bool:
        msg = EmailMessage()
        msg["From"] = self.config.email_de
        msg["To"] = self.config.email_para
        msg["Subject"] = assunto
        msg.set_content(corpo + "\n— CardioIA, monitoramento contínuo (mensagem automática)\n")
        erro = None
        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=5) as smtp:
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            erro = f"{type(e).__name__}: {e}"
            log.error("[EMAIL] falhou: %s | %s", assunto, erro)
        else:
            log.info("[EMAIL] enviado: %s", assunto)
        self.repo.registrar_email(paciente=paciente, criado_em=time.time(), tipo=tipo, assunto=assunto,
                                  para=self.config.email_para, status="falhou" if erro else "enviado", erro=erro)
        return erro is None


def _temp(temp: float | None) -> str:
    return "sem leitura" if temp is None else f"{temp:.1f} °C".replace(".", ",")
