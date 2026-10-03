package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class RootCauseAnalysisDTO {
    @SerializedName("failure_location")
    public String failureLocation;

    @SerializedName("triggering_condition")
    public String triggeringCondition;

    @SerializedName("root_cause_hypothesis")
    public String rootCauseHypothesis;

    @SerializedName("affected_component")
    public String affectedComponent;

    @SerializedName("summary")
    public String summary;

    @SerializedName("supporting_evidence")
    public List<EvidenceReferenceDTO> supportingEvidence;

    @SerializedName("contradicting_evidence")
    public List<EvidenceReferenceDTO> contradictingEvidence;

    @SerializedName("confidence")
    public double confidence;

    @SerializedName("uncertainties")
    public List<String> uncertainties;

    public RootCauseAnalysisDTO() {}
}
