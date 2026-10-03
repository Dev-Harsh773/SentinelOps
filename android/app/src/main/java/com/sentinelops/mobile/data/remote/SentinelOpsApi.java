package com.sentinelops.mobile.data.remote;

import com.sentinelops.mobile.data.remote.model.*;
import java.util.List;
import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.PATCH;
import retrofit2.http.POST;
import retrofit2.http.Path;
import retrofit2.http.Query;

public interface SentinelOpsApi {

    @GET("/health")
    Call<HealthResponseDTO> getHealth();

    @GET("/projects")
    Call<List<ProjectDTO>> listProjects();

    @GET("/projects/{project_id}")
    Call<ProjectDTO> getProject(@Path("project_id") String projectId);

    @GET("/incidents")
    Call<List<IncidentDTO>> listIncidents();

    @GET("/incidents/{incident_id}")
    Call<IncidentDTO> getIncident(@Path("incident_id") String incidentId);

    @PATCH("/incidents/{incident_id}/status")
    Call<IncidentDTO> updateIncidentStatus(
        @Path("incident_id") String incidentId,
        @Body IncidentStatusUpdateRequestDTO request
    );

    @GET("/incidents/{incident_id}/evidence")
    Call<List<EvidenceDTO>> listIncidentEvidence(@Path("incident_id") String incidentId);

    @GET("/incidents/{incident_id}/investigation")
    Call<InvestigationResponseDTO> getIncidentInvestigation(@Path("incident_id") String incidentId);

    @GET("/incidents/{incident_id}/remediation")
    Call<RemediationProposalResponseDTO> getIncidentRemediation(@Path("incident_id") String incidentId);

    @GET("/connectors")
    Call<List<ConnectorResponseDTO>> listConnectors(@Query("project_id") String projectId);

    @POST("/connectors/{connector_id}/test")
    Call<ConnectorTestResultDTO> testConnector(@Path("connector_id") String connectorId);

    @GET("/notifications")
    Call<List<NotificationResponseDTO>> listNotifications(
        @Query("project_id") String projectId,
        @Query("read_status") String readStatus,
        @Query("channel") String channel,
        @Query("delivery_status") String deliveryStatus,
        @Query("limit") int limit,
        @Query("offset") int offset
    );

    @PATCH("/notifications/{notification_id}/read")
    Call<NotificationResponseDTO> markNotificationRead(@Path("notification_id") String notificationId);

    @POST("/notifications/mark-all-read")
    Call<MarkAllReadResponseDTO> markAllNotificationsRead(@Query("project_id") String projectId);

    @POST("/notifications/{notification_id}/retry")
    Call<NotificationResponseDTO> retryNotification(@Path("notification_id") String notificationId);
}
