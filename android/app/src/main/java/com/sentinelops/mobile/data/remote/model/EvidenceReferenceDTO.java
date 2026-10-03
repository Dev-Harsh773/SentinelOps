package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class EvidenceReferenceDTO {
    @SerializedName("type")
    public String type; // "runtime", "code", "git_commit"

    @SerializedName("id")
    public String id;

    @SerializedName("description")
    public String description;

    public EvidenceReferenceDTO() {}
}
