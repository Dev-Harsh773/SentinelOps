package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class IncidentDTO {
    @SerializedName("id")
    public String id;

    @SerializedName("title")
    public String title;

    @SerializedName("summary")
    public String summary;

    @SerializedName("severity")
    public String severity; // "low", "medium", "high", "critical"

    @SerializedName("status")
    public String status;   // "open", "investigating", "resolved", "closed"

    @SerializedName("service")
    public String service;

    @SerializedName("environment")
    public String environment;

    @SerializedName("created_at")
    public String createdAt;

    @SerializedName("updated_at")
    public String updatedAt;

    @SerializedName("project_id")
    public String projectId;

    public IncidentDTO() {}
}
