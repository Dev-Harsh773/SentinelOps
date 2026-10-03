package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class RemediationProposalResponseDTO {
    @SerializedName("remediation_id")
    public String remediationId;

    @SerializedName("incident_id")
    public String incidentId;

    @SerializedName("investigation_id")
    public String investigationId;

    @SerializedName("status")
    public String status; // "draft", "validated", "approved", "rejected", etc.

    @SerializedName("summary")
    public String summary;

    @SerializedName("target_files")
    public List<String> targetFiles;

    @SerializedName("target_symbols")
    public List<String> targetSymbols;

    @SerializedName("proposed_changes")
    public List<ProposedChangeDTO> proposedChanges;

    @SerializedName("rationale")
    public String rationale;

    @SerializedName("risks")
    public List<String> risks;

    @SerializedName("validation_steps")
    public List<String> validationSteps;

    @SerializedName("confidence")
    public double confidence;

    @SerializedName("created_at")
    public String createdAt;

    @SerializedName("updated_at")
    public String updatedAt;

    public RemediationProposalResponseDTO() {}
}
