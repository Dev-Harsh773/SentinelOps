package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class HealthResponseDTO {
    @SerializedName("status")
    public String status;

    @SerializedName("service")
    public String service;

    public HealthResponseDTO() {}

    public HealthResponseDTO(String status, String service) {
        this.status = status;
        this.service = service;
    }
}
