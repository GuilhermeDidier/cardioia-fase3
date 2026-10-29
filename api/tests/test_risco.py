"""Fronteiras dos limiares (iguais aos do firmware e do Node-RED) e níveis."""

import pytest

from api.app.risco import classificar


@pytest.mark.parametrize("bpm,temp,motivos", [
    (120, 36.6, ()), (121, 36.6, ("taquicardia",)),
    (50, 36.6, ()), (49, 36.6, ("bradicardia",)),
    (78, 38.0, ()), (78, 38.1, ("febre",)),
    (78, 35.0, ()), (78, 34.9, ("hipotermia",)),
    (130, 38.4, ("taquicardia", "febre")),
])
def test_limiares(bpm, temp, motivos):
    assert classificar(bpm, temp).motivos == motivos


def test_sem_temperatura_e_erro_de_sensor_e_nao_febre():
    risco = classificar(78, None)
    assert risco.erro_sensor and not risco.alerta


def test_niveis():
    assert classificar(78, 36.6).nivel == "normal"
    assert classificar(130, 36.6).nivel == "atencao"
    assert classificar(151, 36.6).nivel == "critico"          # valor extremo
    assert classificar(130, 38.4).nivel == "critico"          # dois motivos
    assert classificar(78, 39.6).nivel == "critico"
