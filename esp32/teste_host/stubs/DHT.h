#pragma once
#define DHT22 22
extern float g_temp, g_umid;
struct DHT { DHT(int,int){} void begin(){} float readTemperature(){ return g_temp; } float readHumidity(){ return g_umid; } };
