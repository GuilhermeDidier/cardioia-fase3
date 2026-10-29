#pragma once
struct PubSubClient { PubSubClient(WiFiClient&){} bool connected(){ return false; } };
