#!/bin/sh
# Teste da lógica de resiliência do firmware, rodando no computador (sem ESP32).
# Compila o próprio cardioia_monitor.ino com stubs mínimos do Arduino, no modo
# USAR_MQTT=0 e buffer de 8 posições, e simula 40 s com queda de conexão.
# Requer a biblioteca ArduinoJson instalada (arduino-cli lib install ArduinoJson).
set -e
cd "$(dirname "$0")"
ARDUINOJSON="${ARDUINOJSON:-$(arduino-cli config get directories.user)/libraries/ArduinoJson/src}"
c++ -std=c++17 -Wall -Istubs -I../cardioia_monitor -I"$ARDUINOJSON" teste_resiliencia.cpp -o /tmp/cardioia_teste_host
/tmp/cardioia_teste_host | grep -v '^\[STATUS\]'
