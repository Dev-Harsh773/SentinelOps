package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class ConnectorResponseDTO {
    @SerializedName("connector_id")
    public String connectorId;

    @SerializedName("project_id")
    public String projectId;

    @SerializedName("name")
    public String name;

    @SerializedName("connector_type")
    public String connectorType; // "http_poller", "webhook"

    @SerializedName("config")
    public ConnectorConfigDTO config;

    @SerializedName("status")
    public String status;        // "active", "disabled"

    @SerializedName("created_at")
    public String createdAt;

    @SerializedName("updated_at")
    public String updatedAt;

    @SerializedName("health")
    public ConnectorHealthDTO health;

    public ConnectorResponseDTO() {}
}
