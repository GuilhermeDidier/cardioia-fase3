/*
 * CardioIA — Fase 3: Monitoramento Contínuo (IoT no peito do paciente)
 * FIAP — Inteligência Artificial
 *
 * Wearable cardíaco simulado no Wokwi (ESP32 DevKit v1).
 *
 *   DHT22 (GPIO 15) ........ temperatura corporal + umidade (sensor obrigatório)
 *   Potenciômetro (GPIO 34)  frequência cardíaca simulada, 40–180 bpm (2º sensor)
 *   Botão "Wi-Fi" (GPIO 4) . liga/desliga a conectividade simulada (variável booleana)
 *   LED azul (GPIO 26) ..... aceso = online; piscando = Wi-Fi ligado mas sem broker
 *   LED vermelho (GPIO 27) . aceso enquanto a última leitura for alerta
 *
 * Fluxo: ler → classificar → online? ── sim → enviar para a nuvem
 *                                   └─ não → guardar no buffer local (edge)
 *        ao voltar online, o buffer é sincronizado (mais antigo primeiro)
 *        e cada registro só sai do buffer depois de enviado com sucesso.
 *
 * "Nuvem": todo envio é impresso no Serial com a tag [NUVEM] (Parte 1 do
 * enunciado: "envie via Serial.println") e, com USAR_MQTT = 1, também é
 * publicado no broker MQTT (Parte 2).
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ---------------------------------------------------------------------------
// Configuração
// ---------------------------------------------------------------------------

#ifndef USAR_MQTT
#define USAR_MQTT 1        // 0 = Parte 1 pura (nuvem = Serial, sem rede); 1 = MQTT + eco no Serial
#endif

#ifndef MODO_DEMO
#define MODO_DEMO 1        // 1 = buffer curto, para ver a política de descarte em ~1 min no Wokwi
#endif

// Capacidade do buffer offline. Em produção: 1800 leituras = 1 h sem rede a
// 1 leitura / 2 s (1800 × 16 bytes = 28,8 KB dos ~320 KB de RAM do ESP32).
// No modo demo: 30 leituras = 1 min, para o avaliador ver o buffer encher.
#ifdef CAPACIDADE_BUFFER_OVERRIDE
constexpr uint16_t CAPACIDADE_BUFFER = CAPACIDADE_BUFFER_OVERRIDE;
#else
constexpr uint16_t CAPACIDADE_BUFFER = MODO_DEMO ? 30 : 1800;
#endif

constexpr uint32_t INTERVALO_LEITURA_MS = 2000;   // DHT22 lê no máximo a 0,5 Hz
constexpr uint32_t INTERVALO_STATUS_MS = 10000;
constexpr uint32_t INTERVALO_RECONEXAO_MS = 5000;
constexpr uint8_t  SYNC_POR_PASSADA = 10;          // sincroniza em lotes para não travar o loop

// Limiares clínicos (justificativa no relatório da Parte 1)
constexpr float   TEMP_FEBRE_C = 38.0;      // febre: definição clássica e exemplo do enunciado
constexpr float   TEMP_HIPOTERMIA_C = 35.0; // hipotermia: definição padrão
constexpr uint8_t BPM_TAQUICARDIA = 120;    // >100 já é taquicardia; 120 reduz falso alarme em esforço leve
constexpr uint8_t BPM_BRADICARDIA = 50;     // <60 é bradicardia; 50 evita alarmar atletas e sono
constexpr uint8_t BPM_MIN = 40, BPM_MAX = 180;  // faixa mapeada no potenciômetro

// Pinos
constexpr uint8_t PINO_DHT = 15;
constexpr uint8_t PINO_BPM = 34;           // ADC1: o ADC2 não funciona com o Wi-Fi ligado
constexpr uint8_t PINO_BOTAO_WIFI = 4;
constexpr uint8_t PINO_LED_WIFI = 26;
constexpr uint8_t PINO_LED_ALERTA = 27;

// Identificação pseudonimizada: nenhum dado pessoal sai do dispositivo
const char* PACIENTE_ID = "P001";

// Broker público de testes, sem credencial (um projeto Wokwi público exporia
// qualquer senha). Em produção: WiFiClientSecure + porta 8883 + usuário por
// dispositivo. Alternativa se o HiveMQ cair: "test.mosquitto.org".
const char* MQTT_HOST = "broker.hivemq.com";
const uint16_t MQTT_PORT = 1883;
const char* TOPICO_LEITURAS = "cardioia/fase3/g568457/paciente/P001/leituras";
const char* TOPICO_ALERTAS = "cardioia/fase3/g568457/paciente/P001/alertas";
const char* TOPICO_STATUS = "cardioia/fase3/g568457/paciente/P001/status";

// ---------------------------------------------------------------------------
// Leitura e buffer circular
// ---------------------------------------------------------------------------

enum : uint8_t {
  FLAG_ALERTA = 1 << 0,
  FLAG_FEBRE = 1 << 1,
  FLAG_HIPOTERMIA = 1 << 2,
  FLAG_TAQUICARDIA = 1 << 3,
  FLAG_BRADICARDIA = 1 << 4,
  FLAG_ERRO_SENSOR = 1 << 5,
};

struct Leitura {      // 16 bytes por registro
  uint32_t seq;       // sequência monotônica (ordem e conferência no Node-RED)
  uint32_t t_ms;      // millis() no instante da leitura
  int16_t temp_x10;   // 36,7 °C → 367; INT16_MIN = falha do sensor
  uint8_t umid;       // % (255 = falha do sensor)
  uint8_t bpm;
  uint8_t flags;      // FLAG_*
  uint8_t _pad[3];
};

// Fila circular estática (sem heap): o índice lógico 0 é a leitura mais antiga.
Leitura buffer[CAPACIDADE_BUFFER];
uint16_t cabeca = 0;
uint16_t tamanho = 0;
uint32_t descartadasNormais = 0;
uint32_t descartadasAlertas = 0;

Leitura& bufferEm(uint16_t i) { return buffer[(cabeca + i) % CAPACIDADE_BUFFER]; }

// Remove o registro de índice lógico k deslocando os mais antigos uma posição.
void bufferRemover(uint16_t k) {
  for (uint16_t i = k; i > 0; i--) bufferEm(i) = bufferEm(i - 1);
  cabeca = (cabeca + 1) % CAPACIDADE_BUFFER;
  tamanho--;
}

// Política de descarte com o buffer cheio: sai a leitura NORMAL mais antiga.
// Um alerta só é descartado se o buffer inteiro for de alertas.
void bufferArmazenar(const Leitura& l) {
  if (tamanho == CAPACIDADE_BUFFER) {
    int32_t alvo = -1;
    for (uint16_t i = 0; i < tamanho; i++) {
      if (!(bufferEm(i).flags & FLAG_ALERTA)) { alvo = i; break; }
    }
    uint16_t alertasNoBuffer = 0;
    for (uint16_t i = 0; i < tamanho; i++) {
      if (bufferEm(i).flags & FLAG_ALERTA) alertasNoBuffer++;
    }
    if (alvo >= 0) {
      Serial.printf("[BUFFER] cheio (%u/%u): descartada leitura NORMAL seq=%lu; alertas preservados=%u\n",
                    tamanho, CAPACIDADE_BUFFER, (unsigned long)bufferEm(alvo).seq, alertasNoBuffer);
      bufferRemover(alvo);
      descartadasNormais++;
    } else {
      Serial.printf("[BUFFER] AVISO cheio so de alertas: descartado o alerta mais antigo seq=%lu\n",
                    (unsigned long)bufferEm(0).seq);
      bufferRemover(0);
      descartadasAlertas++;
    }
  }
  bufferEm(tamanho) = l;
  tamanho++;
}

// ---------------------------------------------------------------------------
// Estado global
// ---------------------------------------------------------------------------

DHT dht(PINO_DHT, DHT22);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

bool wifiSimuladoLigado = true;   // a "variável booleana" de conectividade pedida no enunciado
bool ultimaLeituraAlerta = false;
bool sincronizando = false;
uint32_t enviadasNaSync = 0;
uint32_t proximaSeq = 1;
uint32_t errosSensor = 0;
uint32_t ultimaLeituraMs = 0;
uint32_t ultimoStatusMs = 0;
uint32_t ultimaTentativaMqttMs = 0;
bool estadoOnlineAnterior = false;
uint16_t tamanhoAnterior = 0;
char clientId[32];

// ---------------------------------------------------------------------------
// Sensores e classificação
// ---------------------------------------------------------------------------

Leitura ler() {
  Leitura l = {};
  l.seq = proximaSeq++;
  l.t_ms = millis();

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    l.temp_x10 = INT16_MIN;
    l.umid = 255;
    l.flags |= FLAG_ERRO_SENSOR;
    errosSensor++;
  } else {
    l.temp_x10 = (int16_t)lroundf(t * 10);
    l.umid = (uint8_t)constrain(lroundf(h), 0, 100);
  }

  // Média de 4 leituras para suavizar o ruído do ADC
  uint32_t soma = 0;
  for (uint8_t i = 0; i < 4; i++) soma += analogRead(PINO_BPM);
  l.bpm = (uint8_t)map(soma / 4, 0, 4095, BPM_MIN, BPM_MAX);
  return l;
}

void classificar(Leitura& l) {
  if (l.bpm > BPM_TAQUICARDIA) l.flags |= FLAG_TAQUICARDIA;
  if (l.bpm < BPM_BRADICARDIA) l.flags |= FLAG_BRADICARDIA;
  // Falha do DHT22 não vira alerta clínico: é registrada como erro do sensor
  if (!(l.flags & FLAG_ERRO_SENSOR)) {
    float t = l.temp_x10 / 10.0f;
    if (t > TEMP_FEBRE_C) l.flags |= FLAG_FEBRE;
    if (t < TEMP_HIPOTERMIA_C) l.flags |= FLAG_HIPOTERMIA;
  }
  if (l.flags & (FLAG_FEBRE | FLAG_HIPOTERMIA | FLAG_TAQUICARDIA | FLAG_BRADICARDIA)) l.flags |= FLAG_ALERTA;
}

// "taquicardia+febre", ou "" se normal
String motivo(const Leitura& l) {
  String m;
  auto add = [&m](const char* s) { if (m.length()) m += "+"; m += s; };
  if (l.flags & FLAG_TAQUICARDIA) add("taquicardia");
  if (l.flags & FLAG_BRADICARDIA) add("bradicardia");
  if (l.flags & FLAG_FEBRE) add("febre");
  if (l.flags & FLAG_HIPOTERMIA) add("hipotermia");
  return m;
}

// ---------------------------------------------------------------------------
// Envio para a nuvem
// ---------------------------------------------------------------------------

// Monta o JSON e envia. Retorna true só se o envio foi aceito; o chamador
// usa isso para decidir se pode apagar o registro do buffer.
bool enviar(const Leitura& l, const char* origem) {
  JsonDocument doc;
  doc["paciente"] = PACIENTE_ID;
  doc["seq"] = l.seq;
  doc["idade_ms"] = millis() - l.t_ms;   // o Node-RED reconstrói o horário da leitura
  if (l.flags & FLAG_ERRO_SENSOR) {
    doc["temp"] = nullptr;
    doc["umid"] = nullptr;
  } else {
    doc["temp"] = l.temp_x10 / 10.0;
    doc["umid"] = l.umid;
  }
  doc["bpm"] = l.bpm;
  doc["alerta"] = (bool)(l.flags & FLAG_ALERTA);
  doc["motivo"] = motivo(l);
  doc["origem"] = origem;
  // pendentes depois deste envio (na sync o próprio registro ainda está no buffer)
  doc["buffer_pendente"] = strcmp(origem, "buffer") == 0 ? tamanho - 1 : tamanho;

  char json[256];
  serializeJson(doc, json, sizeof(json));

#if USAR_MQTT
  bool ok = mqtt.publish(TOPICO_LEITURAS, json);
  if (ok && (l.flags & FLAG_ALERTA)) mqtt.publish(TOPICO_ALERTAS, json);
#else
  bool ok = true;
#endif
  if (ok) {
    Serial.print("[NUVEM] ");
    Serial.println(json);
  }
  return ok;
}

void publicarStatus(bool online);

// Esvazia o buffer em lotes, do mais antigo para o mais novo.
void sincronizar() {
  if (!sincronizando) {
    sincronizando = true;
    enviadasNaSync = 0;
    Serial.printf("[SYNC] iniciando: %u pendentes\n", tamanho);
  }
  for (uint8_t n = 0; n < SYNC_POR_PASSADA && tamanho > 0; n++) {
    if (!enviar(bufferEm(0), "buffer")) {
      Serial.println("[SYNC] envio falhou; registro mantido no buffer para nova tentativa");
      return;
    }
    bufferRemover(0);   // "apaga o local" só depois do envio confirmado
    enviadasNaSync++;
  }
  if (tamanho == 0) {
    Serial.printf("[SYNC] concluida: %lu enviadas; descartadas acumuladas: normais=%lu alertas=%lu; buffer limpo\n",
                  (unsigned long)enviadasNaSync, (unsigned long)descartadasNormais, (unsigned long)descartadasAlertas);
    sincronizando = false;
  }
}

void publicarStatus(bool online) {
  JsonDocument doc;
  doc["online"] = online;
  doc["buffer"] = tamanho;
  doc["capacidade"] = CAPACIDADE_BUFFER;
  doc["descartadas_normais"] = descartadasNormais;
  doc["descartadas_alertas"] = descartadasAlertas;
  doc["erros_sensor"] = errosSensor;
  doc["uptime_s"] = millis() / 1000;
  char json[200];
  serializeJson(doc, json, sizeof(json));
#if USAR_MQTT
  if (mqtt.connected()) mqtt.publish(TOPICO_STATUS, json, true);   // retained: quem assina recebe o último estado
#endif
  Serial.print("[STATUS] ");
  Serial.println(json);
}

// ---------------------------------------------------------------------------
// Conectividade
// ---------------------------------------------------------------------------

void tratarBotao() {
  static bool ultimoNivel = HIGH;
  static uint32_t ultimaMudancaMs = 0;
  bool nivel = digitalRead(PINO_BOTAO_WIFI);
  if (nivel != ultimoNivel && millis() - ultimaMudancaMs > 50) {   // debounce de 50 ms
    ultimaMudancaMs = millis();
    ultimoNivel = nivel;
    if (nivel == LOW) {   // borda de descida = botão pressionado
      wifiSimuladoLigado = !wifiSimuladoLigado;
      Serial.printf("[WIFI] simulado: %s\n", wifiSimuladoLigado ? "LIGADO" : "DESLIGADO");
    }
  }
}

void manterConexao() {
#if USAR_MQTT
  if (!wifiSimuladoLigado) {
    if (mqtt.connected()) {
      // Desconexão limpa não dispara o Last Will, então avisa o offline antes de sair
      publicarStatus(false);
      mqtt.disconnect();
      Serial.println("[MQTT] desconectado (Wi-Fi simulado desligado)");
    }
    return;
  }
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) return;
  if (millis() - ultimaTentativaMqttMs < INTERVALO_RECONEXAO_MS && ultimaTentativaMqttMs != 0) return;
  ultimaTentativaMqttMs = millis();
  Serial.printf("[MQTT] conectando a %s:%u ...\n", MQTT_HOST, MQTT_PORT);
  // Last Will: se o dispositivo cair sem avisar, o broker publica offline por ele
  if (mqtt.connect(clientId, TOPICO_STATUS, 0, true, "{\"online\":false,\"motivo\":\"lwt\"}")) {
    Serial.printf("[MQTT] conectado como %s\n", clientId);
  } else {
    Serial.printf("[MQTT] falha (estado %d); nova tentativa em %lus\n", mqtt.state(),
                  (unsigned long)(INTERVALO_RECONEXAO_MS / 1000));
  }
#endif
}

bool estaOnline() {
#if USAR_MQTT
  return wifiSimuladoLigado && mqtt.connected();
#else
  return wifiSimuladoLigado;
#endif
}

void atualizarLeds(bool online) {
  bool piscando = wifiSimuladoLigado && !online && (millis() / 250) % 2;
  digitalWrite(PINO_LED_WIFI, online || piscando);
  digitalWrite(PINO_LED_ALERTA, ultimaLeituraAlerta);
}

// ---------------------------------------------------------------------------
// setup / loop
// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  pinMode(PINO_BOTAO_WIFI, INPUT_PULLUP);
  pinMode(PINO_LED_WIFI, OUTPUT);
  pinMode(PINO_LED_ALERTA, OUTPUT);
  analogReadResolution(12);
  dht.begin();

  Serial.printf("[BOOT] CardioIA Fase 3 | paciente=%s | modo=%s | buffer=%u leituras (%lus offline) | leitura a cada %lus\n",
                PACIENTE_ID, USAR_MQTT ? "MQTT" : "SERIAL", CAPACIDADE_BUFFER,
                (unsigned long)(CAPACIDADE_BUFFER * (INTERVALO_LEITURA_MS / 1000)),
                (unsigned long)(INTERVALO_LEITURA_MS / 1000));
  Serial.printf("[BOOT] alertas: bpm>%u ou bpm<%u, temp>%.1fC ou temp<%.1fC\n",
                BPM_TAQUICARDIA, BPM_BRADICARDIA, TEMP_FEBRE_C, TEMP_HIPOTERMIA_C);

#if USAR_MQTT
  // Client id único: o broker é público e derruba conexões com id repetido
  uint64_t mac = ESP.getEfuseMac();
  snprintf(clientId, sizeof(clientId), "cardioia-%s-%06lx", PACIENTE_ID, (unsigned long)(mac & 0xFFFFFF));
  WiFi.begin("Wokwi-GUEST", "", 6);   // canal 6 acelera a conexão no Wokwi
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  Serial.println("[WIFI] conectando a Wokwi-GUEST ...");
#endif
}

void loop() {
  tratarBotao();
  manterConexao();
#if USAR_MQTT
  mqtt.loop();
#endif
  bool online = estaOnline();

  if (millis() - ultimaLeituraMs >= INTERVALO_LEITURA_MS) {
    ultimaLeituraMs = millis();
    Leitura l = ler();
    classificar(l);
    ultimaLeituraAlerta = l.flags & FLAG_ALERTA;

    if (l.flags & FLAG_ERRO_SENSOR) {
      Serial.printf("[LEITURA] seq=%lu temp=ERRO umid=ERRO bpm=%u (falha do DHT22)\n", (unsigned long)l.seq, l.bpm);
    } else {
      Serial.printf("[LEITURA] seq=%lu temp=%.1fC umid=%u%% bpm=%u estado=%s\n", (unsigned long)l.seq,
                    l.temp_x10 / 10.0, l.umid, l.bpm, ultimaLeituraAlerta ? "ALERTA" : "NORMAL");
    }
    if (ultimaLeituraAlerta) Serial.printf("[ALERTA] %s (bpm=%u temp=%.1fC)\n", motivo(l).c_str(), l.bpm, l.temp_x10 / 10.0);

    // Com dados pendentes, a leitura nova entra no fim da fila para manter a ordem de envio
    if (online && tamanho == 0) {
      if (!enviar(l, "tempo_real")) bufferArmazenar(l);
    } else {
      bufferArmazenar(l);
      if (!online) Serial.printf("[OFFLINE] armazenada localmente (%u/%u)\n", tamanho, CAPACIDADE_BUFFER);
    }
  }

  if (online && tamanho > 0) sincronizar();

  if (online != estadoOnlineAnterior || millis() - ultimoStatusMs >= INTERVALO_STATUS_MS ||
      (tamanho == 0 && tamanhoAnterior > 0)) {
    ultimoStatusMs = millis();
    estadoOnlineAnterior = online;
    publicarStatus(online);
  }
  tamanhoAnterior = tamanho;

  atualizarLeds(online);
}
