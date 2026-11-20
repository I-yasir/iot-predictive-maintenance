// Copy to include/config.h (gitignored) and fill in. Never commit real credentials.
#ifndef PDM_CONFIG_H
#define PDM_CONFIG_H

// --- Wi-Fi (2.4 GHz only) ---
#define WIFI_SSID "your-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// --- MQTT broker (the PC running `docker compose up mosquitto`) ---
#define MQTT_HOST "192.168.1.50"
#define MQTT_PORT 1883
// The broker ACL only lets a device publish for its own asset: username MUST equal ASSET_ID.
#define MQTT_USERNAME ASSET_ID
#define MQTT_PASSWORD "change-me-device"
#define MQTT_TOPIC_PREFIX "pdm/v1"

// --- Identity ---
#define SITE_ID "lab"
#define ASSET_ID "FD001-E001"

// --- HTTP fallback (used after 5 failed broker connects; empty string disables) ---
#define HTTP_INGEST_URL "http://192.168.1.50:8000/api/v1/ingest"
#define INGEST_API_KEY "replace-with-32-plus-random-characters-xxxxxxxx"

// --- Stream ---
#define PUBLISH_INTERVAL_MS 1000   // 1 message (= 1 operating cycle) per second
#define GEN_MODE PDM_MODE_TRAJECTORY  // or PDM_MODE_DISTRIBUTION
#define LOOP_LIFE 1                // 1: start a new life after end-of-life; 0: stop
#define GEN_SEED 0                 // 0: derive from the chip's MAC address
#define LED_PIN 2                  // on-board LED of most ESP32 DevKit boards

#endif
