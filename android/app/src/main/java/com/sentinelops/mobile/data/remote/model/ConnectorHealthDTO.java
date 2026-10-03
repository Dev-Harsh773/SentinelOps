package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class ConnectorHealthDTO {
    @SerializedName("connector_id")
    public String connectorId;

    @SerializedName("operational_status")
    public String operationalStatus; // "healthy", "degraded", "errored"

    @SerializedName("target_status")
    public String targetStatus;      // "healthy", "unhealthy", "unknown"

    @SerializedName("last_poll_at")
    public String lastPollAt;

    @SerializedName("last_success_at")
    public String lastSuccessAt;

    @SerializedName("consecutive_operational_errors")
    public int consecutiveOperationalErrors;

    @SerializedName("last_operational_error")
    public String lastOperationalError;

    @SerializedName("last_target_error")
    public String lastTargetError;

    public ConnectorHealthDTO() {}
}
