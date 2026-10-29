"""Verificação de risco de uma leitura de sinais vitais.

Os limiares são os mesmos do firmware (esp32/cardioia_monitor/cardioia_monitor.ino)
e do nó "avalia alerta" do Node-RED: a API reavalia cada leitura em vez de
confiar só no campo "alerta" que vem do ESP32.
"""

from dataclasses import dataclass

LIMIARES = {
    "taquicardia": 120,   # bpm >
    "bradicardia": 50,    # bpm <
    "febre": 38.0,        # °C >
    "hipotermia": 35.0,   # °C <
}

# Valores que, sozinhos, já pedem resposta imediata (nível crítico)
EXTREMOS = {"bpm_alto": 150, "bpm_baixo": 40, "temp_alta": 39.5, "temp_baixa": 34.0}


@dataclass(frozen=True)
class Risco:
    motivos: tuple[str, ...]
    nivel: str            # normal | atencao | critico
    erro_sensor: bool

    @property
    def alerta(self) -> bool:
        return bool(self.motivos)

    @property
    def motivo(self) -> str:
        return "+".join(self.motivos)


def classificar(bpm: int, temp: float | None) -> Risco:
    motivos = []
    if bpm > LIMIARES["taquicardia"]:
        motivos.append("taquicardia")
    if bpm < LIMIARES["bradicardia"]:
        motivos.append("bradicardia")
    # Sem temperatura (falha do DHT22) não há febre nem hipotermia: é erro do sensor
    if temp is not None and temp > LIMIARES["febre"]:
        motivos.append("febre")
    if temp is not None and temp < LIMIARES["hipotermia"]:
        motivos.append("hipotermia")

    extremo = (bpm > EXTREMOS["bpm_alto"] or bpm < EXTREMOS["bpm_baixo"]
               or (temp is not None and (temp > EXTREMOS["temp_alta"] or temp < EXTREMOS["temp_baixa"])))
    if not motivos:
        nivel = "normal"
    elif len(motivos) >= 2 or extremo:
        nivel = "critico"
    else:
        nivel = "atencao"
    return Risco(tuple(motivos), nivel, temp is None)
