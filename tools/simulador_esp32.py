"""Simulador do ESP32 do CardioIA para testar o Node-RED sem o Wokwi.

Publica no broker o MESMO formato de mensagem do firmware
(esp32/cardioia_monitor/cardioia_monitor.ino, função enviar()). É uma
ferramenta de teste: as evidências de envio real vêm do ESP32 no Wokwi.

Cenários:
  normal  — sinais vitais estáveis, 1 leitura a cada 2 s
  alerta  — 20 s normal, 30 s de taquicardia + febre, volta ao normal
  queda   — 10 s online, 40 s "offline" (leituras vão para o buffer, com
            alertas no meio) e, ao voltar, sincroniza o buffer em rajada

Uso:
  python tools/simulador_esp32.py --cenario queda
"""

import argparse
import json
import random
import time

import paho.mqtt.client as mqtt

BASE = "cardioia/fase3/g568457/paciente/P001"
INTERVALO_S = 2.0
LIMIARES = {"taquicardia": 120, "bradicardia": 50, "febre": 38.0, "hipotermia": 35.0}


def classificar(bpm, temp):
    motivos = []
    if bpm > LIMIARES["taquicardia"]:
        motivos.append("taquicardia")
    if bpm < LIMIARES["bradicardia"]:
        motivos.append("bradicardia")
    if temp > LIMIARES["febre"]:
        motivos.append("febre")
    if temp < LIMIARES["hipotermia"]:
        motivos.append("hipotermia")
    return "+".join(motivos)


class Esp32Simulado:
    def __init__(self, cliente):
        self.cliente = cliente
        self.seq = 0
        self.buffer = []          # leituras guardadas enquanto "offline"
        self.inicio = time.monotonic()

    def ler(self, alerta=False):
        self.seq += 1
        if alerta:
            bpm, temp = random.randint(128, 140), round(random.uniform(38.2, 38.6), 1)
        else:
            bpm, temp = random.randint(70, 85), round(random.uniform(36.4, 36.9), 1)
        return {"seq": self.seq, "t": time.monotonic(), "bpm": bpm, "temp": temp,
                "umid": random.randint(43, 48)}

    def enviar(self, leitura, origem, pendentes):
        motivo = classificar(leitura["bpm"], leitura["temp"])
        payload = {
            "paciente": "P001",
            "seq": leitura["seq"],
            "idade_ms": int((time.monotonic() - leitura["t"]) * 1000),
            "temp": leitura["temp"],
            "umid": leitura["umid"],
            "bpm": leitura["bpm"],
            "alerta": bool(motivo),
            "motivo": motivo,
            "origem": origem,
            "buffer_pendente": pendentes,
        }
        texto = json.dumps(payload, separators=(",", ":"))
        self.cliente.publish(f"{BASE}/leituras", texto)
        if motivo:
            self.cliente.publish(f"{BASE}/alertas", texto)
        print(f"[NUVEM] {texto}")

    def status(self, online):
        payload = {"online": online, "buffer": len(self.buffer), "capacidade": 30,
                   "descartadas_normais": 0, "descartadas_alertas": 0, "erros_sensor": 0,
                   "uptime_s": int(time.monotonic() - self.inicio)}
        self.cliente.publish(f"{BASE}/status", json.dumps(payload), retain=True)
        print(f"[STATUS] {payload}")

    def ciclo(self, segundos, online, alerta=lambda i: False):
        for i in range(int(segundos / INTERVALO_S)):
            leitura = self.ler(alerta(i))
            if online:
                self.enviar(leitura, "tempo_real", 0)
            else:
                self.buffer.append(leitura)
                print(f"[OFFLINE] armazenada ({len(self.buffer)})")
            time.sleep(INTERVALO_S)

    def sincronizar(self):
        print(f"[SYNC] iniciando: {len(self.buffer)} pendentes")
        while self.buffer:
            leitura = self.buffer.pop(0)
            self.enviar(leitura, "buffer", len(self.buffer))
            time.sleep(0.05)
        print("[SYNC] concluida")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cenario", choices=["normal", "alerta", "queda"], default="normal")
    parser.add_argument("--broker", default="broker.hivemq.com")
    parser.add_argument("--duracao", type=float, default=30, help="segundos do cenário normal")
    args = parser.parse_args()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"cardioia-simulador-{random.randint(0, 99999)}")
    cliente.connect(args.broker, 1883, keepalive=60)
    cliente.loop_start()
    esp = Esp32Simulado(cliente)
    esp.status(True)

    if args.cenario == "normal":
        esp.ciclo(args.duracao, online=True)
    elif args.cenario == "alerta":
        esp.ciclo(20, online=True)
        esp.ciclo(30, online=True, alerta=lambda i: True)
        esp.ciclo(16, online=True)
    else:
        esp.ciclo(10, online=True)
        esp.status(False)
        esp.ciclo(40, online=False, alerta=lambda i: 6 <= i < 10)
        esp.status(True)
        esp.sincronizar()
        esp.status(True)
        esp.ciclo(10, online=True)

    time.sleep(1)
    cliente.loop_stop()
    cliente.disconnect()


if __name__ == "__main__":
    main()
