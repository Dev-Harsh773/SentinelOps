package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class ConnectorTestResultDTO {
    @SerializedName("status")
    public String status; // "success", "degraded", "error"

    @SerializedName("status_code")
    public Integer statusCode;

    @SerializedName("latency_ms")
    public Double latencyMs;

    @SerializedName("url")
    public String url;

    @SerializedName("message")
    public String message;

    public ConnectorTestResultDTO() {}
}
