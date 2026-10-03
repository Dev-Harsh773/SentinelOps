package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class IncidentStatusUpdateRequestDTO {
    @SerializedName("status")
    public String status;

    public IncidentStatusUpdateRequestDTO() {}

    public IncidentStatusUpdateRequestDTO(String status) {
        this.status = status;
    }
}
