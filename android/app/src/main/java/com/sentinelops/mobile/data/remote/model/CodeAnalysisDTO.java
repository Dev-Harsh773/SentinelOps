package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class CodeAnalysisDTO {
    @SerializedName("relevant_symbols")
    public List<String> relevantSymbols;

    @SerializedName("relevant_files")
    public List<String> relevantFiles;

    @SerializedName("code_observations")
    public List<String> codeObservations;

    @SerializedName("possible_relationship_to_failure")
    public List<String> possibleRelationshipToFailure;

    @SerializedName("missing_code_context")
    public List<String> missingCodeContext;

    public CodeAnalysisDTO() {}
}
