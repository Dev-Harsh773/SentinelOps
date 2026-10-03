package com.sentinelops.mobile.data.remote.model;

import com.google.gson.JsonObject;
import com.google.gson.annotations.SerializedName;

public class NotificationResponseDTO {
    @SerializedName("notification_id")
    public String notificationId;

    @SerializedName("project_id")
    public String projectId;

    @SerializedName("incident_id")
    public String incidentId;

    @SerializedName("subscription_id")
    public String subscriptionId;

    @SerializedName("notification_type")
    public String notificationType; // "incident_created", "incident_status_changed", etc.

    @SerializedName("severity")
    public String severity;          // "low", "medium", "high", "critical"

    @SerializedName("title")
    public String title;

    @SerializedName("message")
    public String message;

    @SerializedName("payload")
    public JsonObject payload;

    @SerializedName("channel")
    public String channel;           // "webhook", "local_feed"

    @SerializedName("recipient")
    public String recipient;

    @SerializedName("delivery_status")
    public String deliveryStatus;    // "pending", "delivering", "delivered", "failed"

    @SerializedName("read_status")
    public String readStatus;        // "unread", "read"

    @SerializedName("attempt_count")
    public int attemptCount;

    @SerializedName("next_attempt_at")
    public String nextAttemptAt;

    @SerializedName("last_attempt_at")
    public String lastAttemptAt;

    @SerializedName("delivered_at")
    public String deliveredAt;

    @SerializedName("read_at")
    public String readAt;

    @SerializedName("failure_reason")
    public String failureReason;

    @SerializedName("created_at")
    public String createdAt;

    @SerializedName("updated_at")
    public String updatedAt;

    public NotificationResponseDTO() {}
}
