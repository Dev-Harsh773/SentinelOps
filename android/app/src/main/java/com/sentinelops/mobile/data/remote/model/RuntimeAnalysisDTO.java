package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class RuntimeAnalysisDTO {
    @SerializedName("observed_failures")
    public List<String> observedFailures;

    @SerializedName("service")
    public String service;

    @SerializedName("endpoint")
    public String endpoint;

    @SerializedName("exception_type")
    public String exceptionType;

    @SerializedName("important_messages")
    public List<String> importantMessages;

    @SerializedName("request_ids")
    public List<String> requestIds;

    @SerializedName("timeline")
    public List<String> timeline;

    @SerializedName("initial_hypotheses")
    public List<String> initialHypotheses;

    @SerializedName("missing_information")
    public List<String> missingInformation;

    public RuntimeAnalysisDTO() {}
}
