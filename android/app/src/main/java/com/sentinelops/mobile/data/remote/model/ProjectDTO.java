package com.sentinelops.mobile.data.remote.model;

import com.google.gson.annotations.SerializedName;

public class ProjectDTO {
    @SerializedName("project_id")
    public String projectId;

    @SerializedName("name")
    public String name;

    @SerializedName("description")
    public String description;

    @SerializedName("workspace_path")
    public String workspacePath;

    @SerializedName("is_git")
    public boolean isGit;

    @SerializedName("default_branch")
    public String defaultBranch;

    @SerializedName("status")
    public String status; // "registered", "ready", "error"

    @SerializedName("created_at")
    public String createdAt;

    @SerializedName("updated_at")
    public String updatedAt;

    @SerializedName("last_indexed_at")
    public String lastIndexedAt;

    @SerializedName("index_version")
    public String indexVersion;

    @SerializedName("error_message")
    public String errorMessage;

    @SerializedName("last_index_error")
    public String lastIndexError;

    public ProjectDTO() {}
}
