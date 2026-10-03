package com.sentinelops.mobile.data.remote.model;

import com.google.gson.JsonObject;
import com.google.gson.annotations.SerializedName;

public class EvidenceDTO {
    @SerializedName("id")
    public String id;

    @SerializedName("incident_id")
    public String incidentId;

    @SerializedName("type")
    public String type; // "runtime_log", "health_check"

    @SerializedName("source")
    public String source;

    @SerializedName("timestamp")
    public String timestamp;

    @SerializedName("service")
    public String service;

    @SerializedName("request_id")
    public String requestId;

    @SerializedName("trace_id")
    public String traceId;

    @SerializedName("level")
    public String level; // "ERROR", "WARNING", "INFO"

    @SerializedName("event")
    public String event;

    @SerializedName("message")
    public String message;

    @SerializedName("endpoint")
    public String endpoint;

    @SerializedName("exception_type")
    public String exceptionType;

    @SerializedName("metadata")
    public JsonObject metadata;

    @SerializedName("created_at")
    public String createdAt;

    public EvidenceDTO() {}
}
