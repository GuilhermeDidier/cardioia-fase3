#pragma once
#define WL_CONNECTED 3
struct WiFiClient {};
struct WiFiStub { int status(){ return WL_CONNECTED; } void begin(const char*,const char*,int){} }; extern WiFiStub WiFi;
