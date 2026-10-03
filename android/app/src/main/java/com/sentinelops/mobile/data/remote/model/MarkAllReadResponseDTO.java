package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class MarkAllReadResponseDTO {
    @SerializedName("marked_read_count")
    public int markedReadCount;

    public MarkAllReadResponseDTO() {}

    public MarkAllReadResponseDTO(int markedReadCount) {
        this.markedReadCount = markedReadCount;
    }
}
