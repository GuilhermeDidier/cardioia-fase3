#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <cmath>
#include <cstring>
#include <climits>
#include <string>
#include <algorithm>
#define HIGH 1
#define LOW 0
#define INPUT_PULLUP 2
#define OUTPUT 1
extern uint32_t g_millis; extern int g_pin[64]; extern std::string g_serial;
inline uint32_t millis(){ return g_millis; }
inline int digitalRead(int p){ return g_pin[p]; }
inline void digitalWrite(int p,int v){ g_pin[p]=v; }
inline void pinMode(int,int){}
inline int analogRead(int p){ return g_pin[p]; }
inline void analogReadResolution(int){}
inline long map(long x,long a,long b,long c,long d){ return (x-a)*(d-c)/(b-a)+c; }
template<class T,class L,class H> T constrain(T x,L l,H h){ return x<l?l:(x>h?h:x); }
class String : public std::string { public: String(){} String(const char*s):std::string(s){} String(const std::string&s):std::string(s){}
  String& operator+=(const char*s){ append(s); return *this; } unsigned length() const { return size(); } };
struct SerialStub { void begin(int){}
  void print(const char*s){ g_serial+=s; } void println(const char*s){ g_serial+=s; g_serial+="\n"; }
  void printf(const char*f,...){ char b[512]; va_list a; va_start(a,f); vsnprintf(b,sizeof b,f,a); va_end(a); g_serial+=b; } };
extern SerialStub Serial;
struct EspStub { uint64_t getEfuseMac(){ return 0xABCDEF; } }; extern EspStub ESP;
