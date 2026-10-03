package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class ProposedChangeDTO {
    @SerializedName("file_path")
    public String filePath;

    @SerializedName("change_type")
    public String changeType; // "modify", "add", "remove", "configuration"

    @SerializedName("description")
    public String description;

    @SerializedName("reason")
    public String reason;

    @SerializedName("symbol")
    public String symbol;

    public ProposedChangeDTO() {}
}
