// Teste de host da política de resiliência (ver rodar.sh).
// Roteiro: 2 leituras online → Wi-Fi OFF → 3 normais, 3 taquicardias, 1 febre,
// 7 normais (estoura o buffer de 8) → Wi-Fi ON → sincronização.
// Esperado: os 4 alertas chegam à nuvem, só normais são descartadas, ordem preservada.
#include "Arduino.h"
#include "WiFi.h"
#include "DHT.h"
uint32_t g_millis=0; int g_pin[64]; std::string g_serial; SerialStub Serial; EspStub ESP; WiFiStub WiFi; float g_temp=36.6, g_umid=45;
#define USAR_MQTT 0
#define CAPACIDADE_BUFFER_OVERRIDE 8
#include "cardioia_monitor.ino"   // o firmware de verdade, não uma cópia
#include <iostream>
static void avancar(uint32_t ms){ for(uint32_t i=0;i<ms;i+=10){ g_millis+=10; loop(); } }
static void apertar(){ g_pin[PINO_BOTAO_WIFI]=LOW; avancar(100); g_pin[PINO_BOTAO_WIFI]=HIGH; avancar(100); }
static int conta(const std::string& s,const std::string& sub){ int n=0; for(size_t p=0;(p=s.find(sub,p))!=std::string::npos;p+=sub.size()) n++; return n; }
int main(){
  g_pin[PINO_BOTAO_WIFI]=HIGH; g_pin[PINO_BPM]=1000;
  setup(); avancar(4100);
  apertar();
  avancar(6000);
  g_pin[PINO_BPM]=4000; avancar(6000);
  g_pin[PINO_BPM]=1000; g_temp=38.6; avancar(2000);
  g_temp=36.6; avancar(14000);
  std::string antes=g_serial;
  apertar(); avancar(3000);
  std::cout<<g_serial<<"\n==== VERIFICACOES ====\n";
  auto sync=g_serial.substr(antes.size());
  int alertasSync=conta(sync,"\"alerta\":true,");
  printf("alertas armazenados=4, alertas sincronizados=%d\n", alertasSync);
  printf("descartadas normais=%lu alertas=%lu, buffer final=%u\n",(unsigned long)descartadasNormais,(unsigned long)descartadasAlertas,tamanho);
  printf("sync concluida: %s\n", sync.find("[SYNC] concluida")!=std::string::npos?"sim":"NAO");
  long last=-1; bool ordem=true; size_t p=0; while((p=sync.find("\"seq\":",p))!=std::string::npos){ long s=atol(sync.c_str()+p+6); if(s<=last) ordem=false; last=s; p+=6; }
  printf("ordem crescente na sync: %s\n", ordem?"sim":"NAO");
  bool ok = alertasSync==4 && descartadasAlertas==0 && tamanho==0 && ordem && descartadasNormais>0;
  printf("RESULTADO: %s\n", ok?"PASSOU":"FALHOU"); return ok?0:1;
}
