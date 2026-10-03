package com.sentinelops.mobile.data.remote;

import static org.junit.Assert.*;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.sentinelops.mobile.data.remote.model.*;
import org.junit.Before;
import org.junit.Test;

public class DTOJsonSerializationTest {

    private Gson gson;

    @Before
    public void setUp() {
        gson = new GsonBuilder().create();
    }

    @Test
    public void testHealthResponseSerialization() {
        String json = "{\"status\": \"ok\", \"service\": \"sentinelops\"}";
        HealthResponseDTO dto = gson.fromJson(json, HealthResponseDTO.class);
        assertNotNull(dto);
        assertEquals("ok", dto.status);
        assertEquals("sentinelops", dto.service);
    }

    @Test
    public void testProjectDTOSerialization() {
        String json = "{" +
            "\"project_id\": \"proj-123\"," +
            "\"name\": \"Core Service\"," +
            "\"description\": \"Main backend repo\"," +
            "\"workspace_path\": \"/var/sentinel/core\"," +
            "\"is_git\": true," +
            "\"default_branch\": \"main\"," +
            "\"status\": \"ready\"," +
            "\"created_at\": \"2026-10-01T10:00:00Z\"," +
            "\"updated_at\": \"2026-10-01T12:00:00Z\"," +
            "\"last_indexed_at\": \"2026-10-01T12:30:00Z\"," +
            "\"index_version\": \"v1.2\"" +
            "}";
        ProjectDTO dto = gson.fromJson(json, ProjectDTO.class);
        assertNotNull(dto);
        assertEquals("proj-123", dto.projectId);
        assertEquals("Core Service", dto.name);
        assertTrue(dto.isGit);
        assertEquals("2026-10-01T12:30:00Z", dto.lastIndexedAt);
    }

    @Test
    public void testIncidentDTOSerialization() {
        String json = "{" +
            "\"id\": \"inc-abc\"," +
            "\"title\": \"Elevated 500 error rates\"," +
            "\"summary\": \"High error rates observed\"," +
            "\"severity\": \"critical\"," +
            "\"status\": \"open\"," +
            "\"service\": \"checkout\"," +
            "\"environment\": \"production\"," +
            "\"created_at\": \"2026-10-02T15:00:00Z\"," +
            "\"updated_at\": \"2026-10-02T15:05:00Z\"," +
            "\"project_id\": \"proj-123\"" +
            "}";
        IncidentDTO dto = gson.fromJson(json, IncidentDTO.class);
        assertNotNull(dto);
        assertEquals("inc-abc", dto.id);
        assertEquals("critical", dto.severity);
        assertEquals("open", dto.status);
        assertEquals("checkout", dto.service);
    }

    @Test
    public void testEvidenceDTOSerializationWithJsonObject() {
        String json = "{" +
            "\"id\": \"evi-001\"," +
            "\"incident_id\": \"inc-abc\"," +
            "\"type\": \"runtime_log\"," +
            "\"source\": \"app.log\"," +
            "\"timestamp\": \"2026-10-02T15:01:00Z\"," +
            "\"service\": \"checkout\"," +
            "\"level\": \"ERROR\"," +
            "\"event\": \"database.timeout\"," +
            "\"message\": \"Connection pool exhausted\"," +
            "\"metadata\": {\"host\": \"pod-12\", \"attempt\": 3}," +
            "\"created_at\": \"2026-10-02T15:02:00Z\"" +
            "}";
        EvidenceDTO dto = gson.fromJson(json, EvidenceDTO.class);
        assertNotNull(dto);
        assertEquals("evi-001", dto.id);
        assertEquals("runtime_log", dto.type);
        assertEquals("ERROR", dto.level);
        assertNotNull(dto.metadata);
        assertEquals("pod-12", dto.metadata.get("host").getAsString());
        assertEquals(3, dto.metadata.get("attempt").getAsInt());
    }

    @Test
    public void testInvestigationDTOSerialization() {
        String json = "{" +
            "\"investigation_id\": \"inv-999\"," +
            "\"incident_id\": \"inc-abc\"," +
            "\"status\": \"completed\"," +
            "\"created_at\": \"2026-10-02T15:05:00Z\"," +
            "\"code_results\": [{\"file\": \"db.py\", \"line\": 42}]," +
            "\"rca\": {" +
            "  \"failure_location\": \"pool.py\"," +
            "  \"triggering_condition\": \"connections >= 50\"," +
            "  \"root_cause_hypothesis\": \"Starvation of DB pool\"," +
            "  \"confidence\": 0.88," +
            "  \"summary\": \"Pool exhausted under traffic spike.\"" +
            "}" +
            "}";
        InvestigationResponseDTO dto = gson.fromJson(json, InvestigationResponseDTO.class);
        assertNotNull(dto);
        assertEquals("inv-999", dto.investigationId);
        assertNotNull(dto.codeResults);
        assertEquals(1, dto.codeResults.size());
        assertNotNull(dto.rca);
        assertEquals(0.88, dto.rca.confidence, 0.001);
        assertEquals("Starvation of DB pool", dto.rca.rootCauseHypothesis);
    }

    @Test
    public void testNotificationDTOSerialization() {
        String json = "{" +
            "\"notification_id\": \"notif-1\"," +
            "\"project_id\": \"proj-123\"," +
            "\"notification_type\": \"incident_created\"," +
            "\"severity\": \"high\"," +
            "\"title\": \"New Incident\"," +
            "\"message\": \"Incident detected\"," +
            "\"channel\": \"local_feed\"," +
            "\"recipient\": \"dev-team\"," +
            "\"delivery_status\": \"delivered\"," +
            "\"read_status\": \"unread\"," +
            "\"attempt_count\": 1," +
            "\"failure_reason\": null," +
            "\"payload\": {\"incident_id\": \"inc-abc\"}," +
            "\"created_at\": \"2026-10-02T15:00:00Z\"," +
            "\"updated_at\": \"2026-10-02T15:00:00Z\"" +
            "}";
        NotificationResponseDTO dto = gson.fromJson(json, NotificationResponseDTO.class);
        assertNotNull(dto);
        assertEquals("notif-1", dto.notificationId);
        assertEquals("local_feed", dto.channel);
        assertEquals("delivered", dto.deliveryStatus);
        assertEquals("unread", dto.readStatus);
        assertNotNull(dto.payload);
        assertEquals("inc-abc", dto.payload.get("incident_id").getAsString());
    }

    @Test
    public void testConnectorDTOSerialization() {
        String json = "{" +
            "\"connector_id\": \"conn-http-1\"," +
            "\"project_id\": \"proj-123\"," +
            "\"name\": \"API Gateway Health\"," +
            "\"connector_type\": \"http_poller\"," +
            "\"status\": \"active\"," +
            "\"created_at\": \"2026-10-01T10:00:00Z\"," +
            "\"updated_at\": \"2026-10-01T10:00:00Z\"," +
            "\"config\": {" +
            "  \"service\": \"api-gateway\"," +
            "  \"url\": \"http://api.local/health\"," +
            "  \"method\": \"GET\"," +
            "  \"poll_interval_seconds\": 60," +
            "  \"timeout_seconds\": 10.0" +
            "}," +
            "\"health\": {" +
            "  \"connector_id\": \"conn-http-1\"," +
            "  \"operational_status\": \"healthy\"," +
            "  \"target_status\": \"healthy\"," +
            "  \"consecutive_operational_errors\": 0" +
            "}" +
            "}";
        ConnectorResponseDTO dto = gson.fromJson(json, ConnectorResponseDTO.class);
        assertNotNull(dto);
        assertEquals("conn-http-1", dto.connectorId);
        assertEquals("http_poller", dto.connectorType);
        assertNotNull(dto.health);
        assertEquals("healthy", dto.health.operationalStatus);
        assertEquals("healthy", dto.health.targetStatus);
    }
}
