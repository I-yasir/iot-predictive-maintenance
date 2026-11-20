// PdM-Live ESP32 synthetic telemetry streamer (Mode 2) — plan P2.6, state machine docs/02 §5.
//
// Streams TelemetryPayload v1 (docs/04 §5.2) generated from the C-MAPSS-derived profile over Wi-Fi:
// MQTT (PubSubClient) primary, HTTP POST fallback, 64-message ring buffer while offline.
// No physical sensors are read (PRD non-goal 2).
#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <time.h>

#include "profile_fd001.h"
#include "pdm_generator.h"

#if __has_include("config.h")
#include "config.h"
#else
#warning "include/config.h not found - using config.example.h (copy it and fill in your Wi-Fi/broker)"
#include "config.example.h"
#endif

#define FW_VERSION "esp32-pdm/0.1.0"
#define RING_SIZE 64
#define MQTT_BUFFER 1024
#define MQTT_FAILS_BEFORE_HTTP 5
#define MQTT_RETRY_FROM_HTTP_MS 60000UL

enum State { BOOT, WIFI_CONNECTING, NTP_SYNC, BROKER_CONNECTING, STREAMING, HTTP_FALLBACK, BUFFERING, END_OF_LIFE_IDLE };
static const char* STATE_NAMES[] = {"BOOT", "WIFI_CONNECTING", "NTP_SYNC", "BROKER_CONNECTING",
                                    "STREAMING", "HTTP_FALLBACK", "BUFFERING", "END_OF_LIFE_IDLE"};

static WiFiClient wifiClient;
static PubSubClient mqtt(wifiClient);
static PdmGenerator* gen = nullptr;
static State state = BOOT;
static char topicTelemetry[96], topicStatus[96], topicAck[96];
static char deviceId[13];
static uint32_t seq = 0;
static unsigned long lastPublish = 0, nextWifiTry = 0, nextBrokerTry = 0, httpSince = 0;
static uint32_t wifiBackoffMs = 1000, brokerBackoffMs = 1000;
static int brokerFails = 0;
static uint32_t acks = 0, sent = 0, dropped = 0;

// ---------------------------------------------------------------- ring buffer (offline storage)
static String ring[RING_SIZE];
static int ringHead = 0, ringCount = 0;
static void ringPush(const String& s) {
  if (ringCount == RING_SIZE) {  // overwrite oldest; harness sees the gap via seq
    ringHead = (ringHead + 1) % RING_SIZE;
    ringCount--;
    dropped++;
  }
  ring[(ringHead + ringCount) % RING_SIZE] = s;
  ringCount++;
}
static bool ringPop(String& out) {
  if (!ringCount) return false;
  out = ring[ringHead];
  ring[ringHead] = String();
  ringHead = (ringHead + 1) % RING_SIZE;
  ringCount--;
  return true;
}

// ---------------------------------------------------------------- helpers
static void setState(State s) {
  if (s == state) return;
  Serial.printf("[%8lu] state %s -> %s\n", millis(), STATE_NAMES[state], STATE_NAMES[s]);
  state = s;
}

static void led() {
  unsigned long t = millis();
  bool on;
  switch (state) {
    case STREAMING: on = true; break;                                    // solid
    case WIFI_CONNECTING: on = (t / 500) % 2; break;                     // slow blink
    case BROKER_CONNECTING: on = (t / 125) % 2; break;                   // fast blink
    case BUFFERING: case HTTP_FALLBACK: on = (t % 1000) < 100 || ((t % 1000) > 200 && (t % 1000) < 300); break;  // double
    default: on = false;
  }
  digitalWrite(LED_PIN, on ? HIGH : LOW);
}

static void isoNow(char* buf, size_t n) {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  if (tv.tv_sec < 1700000000) { buf[0] = '\0'; return; }  // clock not synced
  struct tm tm;
  gmtime_r(&tv.tv_sec, &tm);
  size_t len = strftime(buf, n, "%Y-%m-%dT%H:%M:%S", &tm);
  snprintf(buf + len, n - len, ".%03ldZ", (long)(tv.tv_usec / 1000));
}

static String buildPayload() {
  double v[PDM_N_CHANNELS];
  int cycle = gen->next(v);
  seq++;
  JsonDocument doc;
  doc["schema_version"] = "1.0";
  char msgId[40];
  snprintf(msgId, sizeof msgId, "esp32-%s-%06lu", deviceId, (unsigned long)seq);
  doc["msg_id"] = msgId;
  doc["site_id"] = SITE_ID;
  doc["asset_id"] = ASSET_ID;
  doc["profile"] = PDM_PROFILE_NAME;
  doc["source"] = "ESP32";
  doc["seq"] = seq;
  doc["cycle"] = cycle;
  char ts[32];
  isoNow(ts, sizeof ts);
  if (ts[0]) doc["ts"] = ts;  // omitted when NTP failed: server time is used
  JsonObject settings = doc["settings"].to<JsonObject>();
  JsonObject sensors = doc["sensors"].to<JsonObject>();
  for (int j = 0; j < PDM_N_CHANNELS; j++) {
    if (j < PDM_N_SETTINGS) settings[PDM_CHANNELS[j]] = v[j];
    else sensors[PDM_CHANNELS[j]] = v[j];
  }
  JsonObject meta = doc["meta"].to<JsonObject>();
  meta["fw"] = FW_VERSION;
  meta["rssi"] = WiFi.RSSI();
  meta["mode"] = GEN_MODE == PDM_MODE_TRAJECTORY ? "trajectory" : "distribution";
  meta["eol"] = gen->endOfLife();
  meta["true_rul"] = gen->trueRemaining();
  meta["profile_version"] = PDM_PROFILE_VERSION;
  String out;
  serializeJson(doc, out);
  return out;
}

static bool sendMqtt(const String& s) {
  return mqtt.connected() && mqtt.publish(topicTelemetry, s.c_str(), false);
}

static bool sendHttp(const String& s) {
  if (strlen(HTTP_INGEST_URL) == 0) return false;
  HTTPClient http;
  http.setTimeout(5000);
  if (!http.begin(HTTP_INGEST_URL)) return false;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", INGEST_API_KEY);
  int code = http.POST(s);
  http.end();
  return code == 200;  // 4xx = rejected by server (logged there); not retried
}

static void onMqttMessage(char* topic, byte* payload, unsigned int len) {
  if (strcmp(topic, topicAck) == 0) acks++;
}

static void publishStatus(bool online) {
  char buf[160];
  snprintf(buf, sizeof buf, "{\"online\":%s,\"fw\":\"%s\",\"ip\":\"%s\",\"rssi\":%d,\"profile\":\"%s\"}",
           online ? "true" : "false", FW_VERSION, WiFi.localIP().toString().c_str(), WiFi.RSSI(), PDM_PROFILE_NAME);
  mqtt.publish(topicStatus, buf, true);
}

static bool connectBroker() {
  char clientId[40];
  snprintf(clientId, sizeof clientId, "esp32-%s", deviceId);
  static const char* lwt = "{\"online\":false}";
  bool ok = mqtt.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD, topicStatus, 1, true, lwt);
  if (ok) {
    publishStatus(true);
    mqtt.subscribe(topicAck, 0);
  } else {
    Serial.printf("[%8lu] MQTT connect failed, rc=%d\n", millis(), mqtt.state());
  }
  return ok;
}

static void flushRing() {
  String s;
  int n = 0;
  while (ringCount && n < 16) {  // bounded per loop so the main loop stays responsive
    s = ring[ringHead];
    bool ok = state == HTTP_FALLBACK ? sendHttp(s) : sendMqtt(s);
    if (!ok) return;
    ringPop(s);
    sent++;
    n++;
  }
}

// ---------------------------------------------------------------- Arduino entry points
void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  delay(200);
  uint64_t mac = ESP.getEfuseMac();
  snprintf(deviceId, sizeof deviceId, "%06lx", (unsigned long)(mac & 0xFFFFFF));
  uint32_t seed = GEN_SEED ? (uint32_t)GEN_SEED : (uint32_t)(mac ^ (mac >> 32));
  gen = new PdmGenerator(seed, (PdmMode)GEN_MODE);
  snprintf(topicTelemetry, sizeof topicTelemetry, "%s/%s/%s/telemetry", MQTT_TOPIC_PREFIX, SITE_ID, ASSET_ID);
  snprintf(topicStatus, sizeof topicStatus, "%s/%s/%s/status", MQTT_TOPIC_PREFIX, SITE_ID, ASSET_ID);
  snprintf(topicAck, sizeof topicAck, "%s/%s/%s/ack", MQTT_TOPIC_PREFIX, SITE_ID, ASSET_ID);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(MQTT_BUFFER);  // default 256 B is too small for the ~700 B payload
  mqtt.setKeepAlive(30);
  mqtt.setCallback(onMqttMessage);
  Serial.printf("\nPdM-Live %s | profile %s v%s (data %s) | asset %s | device %s | seed %lu | mode %s\n",
                FW_VERSION, PDM_PROFILE_NAME, PDM_PROFILE_VERSION, PDM_PROFILE_DATA_SHA, ASSET_ID, deviceId,
                (unsigned long)seed, GEN_MODE == PDM_MODE_TRAJECTORY ? "trajectory" : "distribution");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);  // we run our own backoff
  setState(WIFI_CONNECTING);
}

void loop() {
  unsigned long now = millis();
  led();
  bool wifiUp = WiFi.status() == WL_CONNECTED;

  switch (state) {
    case WIFI_CONNECTING:
      if (wifiUp) {
        Serial.printf("[%8lu] Wi-Fi up, IP %s, RSSI %d\n", now, WiFi.localIP().toString().c_str(), WiFi.RSSI());
        wifiBackoffMs = 1000;
        setState(NTP_SYNC);
      } else if (now >= nextWifiTry) {
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        nextWifiTry = now + wifiBackoffMs;
        wifiBackoffMs = min<uint32_t>(wifiBackoffMs * 2, 30000);
      }
      break;

    case NTP_SYNC: {
      configTime(0, 0, "pool.ntp.org", "time.google.com");
      struct tm tm;
      if (!getLocalTime(&tm, 5000)) Serial.println("NTP sync failed - sending without ts");
      setState(BROKER_CONNECTING);
      break;
    }

    case BROKER_CONNECTING:
      if (!wifiUp) { setState(WIFI_CONNECTING); break; }
      if (now >= nextBrokerTry) {
        if (connectBroker()) {
          brokerFails = 0;
          brokerBackoffMs = 1000;
          setState(STREAMING);
        } else if (++brokerFails >= MQTT_FAILS_BEFORE_HTTP && strlen(HTTP_INGEST_URL)) {
          httpSince = now;
          setState(HTTP_FALLBACK);
        } else {
          nextBrokerTry = now + brokerBackoffMs;
          brokerBackoffMs = min<uint32_t>(brokerBackoffMs * 2, 30000);
        }
      }
      break;

    case STREAMING:
      mqtt.loop();
      if (!wifiUp) { setState(BUFFERING); break; }
      if (!mqtt.connected()) { setState(BROKER_CONNECTING); break; }
      flushRing();
      break;

    case HTTP_FALLBACK:
      if (!wifiUp) { setState(BUFFERING); break; }
      flushRing();
      if (now - httpSince >= MQTT_RETRY_FROM_HTTP_MS) {  // periodically try to get back to MQTT
        httpSince = now;
        if (connectBroker()) { brokerFails = 0; setState(STREAMING); }
      }
      break;

    case BUFFERING:
      if (wifiUp) setState(BROKER_CONNECTING);
      else if (now >= nextWifiTry) {
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        nextWifiTry = now + wifiBackoffMs;
        wifiBackoffMs = min<uint32_t>(wifiBackoffMs * 2, 30000);
      }
      break;

    case END_OF_LIFE_IDLE:
      mqtt.loop();
      return;

    default:
      break;
  }

  // Produce one cycle per interval regardless of connectivity (the "engine" keeps running).
  if (state != BOOT && state != WIFI_CONNECTING && state != NTP_SYNC && now - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = now;
    bool eolBefore = gen->endOfLife() && gen->cycle() > 0;
    if (eolBefore && !LOOP_LIFE) { setState(END_OF_LIFE_IDLE); return; }
    String msg = buildPayload();
    bool ok = false;
    if (ringCount == 0) ok = state == STREAMING ? sendMqtt(msg) : (state == HTTP_FALLBACK ? sendHttp(msg) : false);
    if (ok) sent++;
    else ringPush(msg);
    if (seq % 10 == 0 || gen->endOfLife())
      Serial.printf("[%8lu] seq %lu cycle %d true_rul %d | sent %lu acks %lu buffered %d dropped %lu | %s\n", now,
                    (unsigned long)seq, gen->cycle(), gen->trueRemaining(), (unsigned long)sent,
                    (unsigned long)acks, ringCount, (unsigned long)dropped, STATE_NAMES[state]);
  }
}
