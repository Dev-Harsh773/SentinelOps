package com.sentinelops.mobile.data.remote.model;

import com.google.gson.JsonObject;
import com.google.gson.annotations.SerializedName;
import java.util.Map;

public class ConnectorConfigDTO {
    @SerializedName("service")
    public String service;

    @SerializedName("environment")
    public String environment;

    @SerializedName("url")
    public String url;

    @SerializedName("method")
    public String method;

    @SerializedName("headers")
    public Map<String, String> headers;

    @SerializedName("poll_interval_seconds")
    public int pollIntervalSeconds;

    @SerializedName("timeout_seconds")
    public double timeoutSeconds;

    @SerializedName("metadata")
    public JsonObject metadata;

    public ConnectorConfigDTO() {}
}
