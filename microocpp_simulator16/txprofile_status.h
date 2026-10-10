// SPDX-License-Identifier: GPL-3.0-only
// Read-only, bounded diagnostics. Does not alter OCPP processing or profiles.
#pragma once
#include <MicroOcpp.h>
#include <array>
#include <ctime>
#include <cstring>
#include <string>

namespace TxProfileStatus {
struct Record {
    bool received = false;
    bool oversized = false;
    std::string payload;
    std::string receivedAt;
};
inline std::array<Record, MO_NUMCONNECTORS>& records() {
    static std::array<Record, MO_NUMCONNECTORS> value;
    return value;
}
inline void observe(JsonObject payload) {
    if (strcmp(payload["csChargingProfiles"]["chargingProfilePurpose"] | "", "TxProfile"))
        return;
    if (!payload["connectorId"].is<int>()) return;
    const int connector = payload["connectorId"];
    if (connector < 0 || connector >= MO_NUMCONNECTORS) return;
    Record &record = records()[connector];
    record = Record{};
    record.received = true;
    const std::time_t now = std::time(nullptr);
    char stamp[32] = {};
    if (const std::tm *utc = std::gmtime(&now))
        std::strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%SZ", utc);
    record.receivedAt = stamp;
    record.oversized = measureJson(payload) > 4096;
    if (!record.oversized) serializeJson(payload, record.payload);
}
inline void setup() {
    setOnReceiveRequest("SetChargingProfile", observe);
}
inline int respond(unsigned connector, char *buffer, size_t size) {
    const Record &record = records()[connector];
    // The raw payload was serialized by ArduinoJson, never interpolated as text.
    std::string json = "{\"received\":";
    json += record.received ? "true" : "false";
    json += ",\"captureStatus\":\"";
    json += !record.received ? "empty" : record.oversized ? "too_large" : "captured";
    json += "\",\"receivedAt\":";
    json += record.receivedAt.empty() ? "null" : "\"" + record.receivedAt + "\"";
    json += ",\"acceptance\":\"not_recorded\",\"payload\":";
    json += record.payload.empty() ? "null" : record.payload;
    json += "}";
    if (json.size() + 1 > size) return 500;
    memcpy(buffer, json.c_str(), json.size() + 1);
    return 200;
}
}
