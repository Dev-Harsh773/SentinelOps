package com.sentinelops.mobile.data.remote.model;

import com.google.gson.JsonArray;
import com.google.gson.annotations.SerializedName;
import java.util.List;

public class InvestigationResponseDTO {
    @SerializedName("investigation_id")
    public String investigationId;

    @SerializedName("incident_id")
    public String incidentId;

    @SerializedName("status")
    public String status;

    @SerializedName("created_at")
    public String createdAt;

    @SerializedName("completed_at")
    public String completedAt;

    @SerializedName("runtime_analysis")
    public RuntimeAnalysisDTO runtimeAnalysis;

    @SerializedName("code_query")
    public String codeQuery;

    @SerializedName("code_results")
    public JsonArray codeResults;

    @SerializedName("code_analysis")
    public CodeAnalysisDTO codeAnalysis;

    @SerializedName("git_context")
    public JsonArray gitContext;

    @SerializedName("rca")
    public RootCauseAnalysisDTO rca;

    @SerializedName("errors")
    public List<String> errors;

    public InvestigationResponseDTO() {}
}
