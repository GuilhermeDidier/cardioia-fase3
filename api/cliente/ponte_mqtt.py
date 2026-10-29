"""Ponte MQTT → REST: repassa à API o que o ESP32 publica no broker.

É um segundo consumidor dos mesmos tópicos do Node-RED (o ESP32 não muda nada).
Assina só "leituras" e "status": o firmware repete cada alerta em "alertas", e
assinar os dois gravaria a mesma leitura duas vezes.

Uso (chave do dispositivo lida de api/.env):
  python -m api.cliente.ponte_mqtt --mqtt
  python -m api.cliente.ponte_mqtt --replay docs/evidencias/broker_mqtt.log --intervalo 0.2

O modo --replay relê um log gravado com `mosquitto_sub -v` (tópico + JSON por linha),
como o da rodada real no Wokwi em docs/evidencias/broker_mqtt.log.
"""

import argparse
import json
import os
import time
from collections import Counter

import httpx
from dotenv import load_dotenv

from api.app.config import RAIZ_REPO
from api.cliente.cliente_rest import ClienteCardioIA

BASE = "cardioia/fase3/g568457/paciente"


def repassar(topico: str, texto: str, cliente: ClienteCardioIA, contagem: Counter):
    partes = topico.split("/")
    if len(partes) != 6 or "/".join(partes[:4]) != BASE:
        contagem["ignorada"] += 1
        return
    paciente, tipo = partes[4], partes[5]
    if tipo == "alertas":   # cópia de uma leitura que já chega em "leituras"
        contagem["alerta_duplicado"] += 1
        return
    try:
        corpo = json.loads(texto)
    except json.JSONDecodeError:
        print(f"[PONTE] JSON inválido em {topico}: {texto[:60]!r}")
        contagem["invalida"] += 1
        return
    try:
        if tipo == "leituras":
            resposta = cliente.enviar_leitura(paciente, corpo)
            risco = resposta["risco"]
            email = " +e-mail" if resposta["email_enviado"] else ""
            print(f"[PONTE] {paciente} seq={corpo.get('seq')} bpm={corpo.get('bpm')} "
                  f"origem={corpo.get('origem')} -> {' '.join([risco['nivel'], *risco['motivos']])}{email}")
            contagem["leitura"] += 1
            contagem["email"] += int(resposta["email_enviado"])
        elif tipo == "status":
            cliente.enviar_status(paciente, corpo)
            print(f"[PONTE] {paciente} status online={corpo.get('online')}")
            contagem["status"] += 1
        else:
            contagem["ignorada"] += 1
    except httpx.HTTPStatusError as e:
        print(f"[PONTE] API recusou {topico}: {e.response.status_code} {e.response.text[:120]}")
        contagem["recusada"] += 1
    except httpx.HTTPError as e:
        # API fora do ar ou lenta: registra e segue; a ponte não pode morrer por isso
        print(f"[PONTE] API inacessível ({type(e).__name__}); mensagem de {topico} perdida")
        contagem["sem_api"] += 1


def replay(caminho: str, cliente: ClienteCardioIA, intervalo: float = 0.0) -> Counter:
    contagem: Counter = Counter()
    with open(caminho, encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            topico, _, texto = linha.partition(" ")
            repassar(topico, texto, cliente, contagem)
            if intervalo:
                time.sleep(intervalo)
    return contagem


def tratar_mensagem(mensagem, cliente: ClienteCardioIA, contagem: Counter):
    """Callback do paho para uma mensagem do broker."""
    if mensagem.retain:
        # status retido é o último que o broker guardou, talvez de horas atrás: a API o
        # carimbaria com o horário de agora, como se fosse novo
        print(f"[PONTE] ignorada mensagem retida em {mensagem.topic}")
        contagem["retida"] += 1
        return
    texto = mensagem.payload.decode("utf-8", errors="replace")
    if texto:
        repassar(mensagem.topic, texto, cliente, contagem)


def ouvir_mqtt(cliente: ClienteCardioIA, broker: str):
    import paho.mqtt.client as mqtt

    contagem: Counter = Counter()

    def ao_conectar(c, _userdata, _flags, codigo, _props):
        print(f"[PONTE] conectada ao broker {broker} (código {codigo}); assinando leituras e status")
        c.subscribe([(f"{BASE}/+/leituras", 0), (f"{BASE}/+/status", 0)])

    def ao_receber(_c, _userdata, mensagem):
        tratar_mensagem(mensagem, cliente, contagem)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"cardioia-ponte-{os.getpid()}")
    c.on_connect = ao_conectar
    c.on_message = ao_receber
    c.connect(broker, 1883, keepalive=60)
    try:
        c.loop_forever()
    except KeyboardInterrupt:
        print(f"[PONTE] encerrada: {dict(contagem)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--mqtt", action="store_true", help="assina o broker ao vivo")
    modo.add_argument("--replay", metavar="LOG", help="relê um log do mosquitto_sub -v")
    parser.add_argument("--broker", default="broker.hivemq.com")
    parser.add_argument("--intervalo", type=float, default=0.0, help="pausa entre linhas no replay (s)")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    load_dotenv(RAIZ_REPO / "api" / ".env")
    cliente = ClienteCardioIA(args.url, os.environ.get("API_CHAVE_DISPOSITIVO", ""))
    if args.replay:
        contagem = replay(args.replay, cliente, args.intervalo)
        print(f"[PONTE] replay concluído: {dict(contagem)}")
    else:
        ouvir_mqtt(cliente, args.broker)


if __name__ == "__main__":
    main()
