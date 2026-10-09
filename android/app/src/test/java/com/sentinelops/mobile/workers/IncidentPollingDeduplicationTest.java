package com.sentinelops.mobile.workers;

import static org.junit.Assert.*;

import android.content.Context;
import android.content.SharedPreferences;
import com.sentinelops.mobile.data.local.AppPreferences;
import com.sentinelops.mobile.data.remote.model.IncidentDTO;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.junit.Before;
import org.junit.Test;
import org.mockito.Mockito;

public class IncidentPollingDeduplicationTest {

    private AppPreferences preferences;
    private SharedPreferences mockPrefs;
    private SharedPreferences.Editor mockEditor;
    private final Set<String> backingSet = new HashSet<>();

    @Before
    public void setUp() {
        Context mockContext = Mockito.mock(Context.class);
        mockPrefs = Mockito.mock(SharedPreferences.class);
        mockEditor = Mockito.mock(SharedPreferences.Editor.class);

        Mockito.when(mockContext.getSharedPreferences(Mockito.anyString(), Mockito.anyInt()))
            .thenReturn(mockPrefs);

        Mockito.when(mockPrefs.getStringSet(Mockito.eq("key_alerted_incident_ids"), Mockito.any()))
            .thenAnswer(inv -> new HashSet<>(backingSet));

        Mockito.when(mockPrefs.edit()).thenReturn(mockEditor);
        Mockito.when(mockEditor.putStringSet(Mockito.eq("key_alerted_incident_ids"), Mockito.any()))
            .thenAnswer(inv -> {
                Set<String> newSet = inv.getArgument(1);
                backingSet.clear();
                if (newSet != null) {
                    backingSet.addAll(newSet);
                }
                return mockEditor;
            });

        preferences = new AppPreferences(mockContext);
        backingSet.clear();
    }

    private IncidentDTO createIncident(String id, String projectId, String status, String severity) {
        IncidentDTO inc = new IncidentDTO();
        inc.id = id;
        inc.projectId = projectId;
        inc.status = status;
        inc.severity = severity;
        inc.title = "Test Incident " + id;
        inc.summary = "Summary for " + id;
        return inc;
    }

    @Test
    public void testNewEligibleIncidentTriggersAlert() {
        IncidentDTO inc = createIncident("inc-001", "order-service", "open", "critical");
        List<IncidentDTO> incidents = Collections.singletonList(inc);

        int alerted = IncidentPollingWorker.evaluateAndNotify(null, preferences, "order-service", incidents);

        assertEquals("New eligible incident should be alerted", 1, alerted);
        assertTrue("Incident ID should be stored in preferences", preferences.isIncidentAlerted("inc-001"));
    }

    @Test
    public void testAlreadyAlertedIncidentSuppressed() {
        preferences.addAlertedIncidentId("inc-001");
        assertTrue(preferences.isIncidentAlerted("inc-001"));

        IncidentDTO inc = createIncident("inc-001", "order-service", "open", "critical");
        List<IncidentDTO> incidents = Collections.singletonList(inc);

        int alerted = IncidentPollingWorker.evaluateAndNotify(null, preferences, "order-service", incidents);

        assertEquals("Already alerted incident should produce 0 alerts", 0, alerted);
    }

    @Test
    public void testWrongProjectIgnored() {
        IncidentDTO inc = createIncident("inc-002", "other-project", "open", "critical");
        List<IncidentDTO> incidents = Collections.singletonList(inc);

        int alerted = IncidentPollingWorker.evaluateAndNotify(null, preferences, "order-service", incidents);

        assertEquals("Incident with mismatched projectId should be ignored", 0, alerted);
        assertFalse(preferences.isIncidentAlerted("inc-002"));
    }

    @Test
    public void testNonAlertingSeverityAndStatusIgnored() {
        List<IncidentDTO> incidents = new ArrayList<>();
        // Low and medium severity
        incidents.add(createIncident("inc-003", "order-service", "open", "low"));
        incidents.add(createIncident("inc-004", "order-service", "open", "medium"));
        // Closed and resolved status
        incidents.add(createIncident("inc-005", "order-service", "resolved", "critical"));
        incidents.add(createIncident("inc-006", "order-service", "closed", "high"));

        int alerted = IncidentPollingWorker.evaluateAndNotify(null, preferences, "order-service", incidents);

        assertEquals("Non-alerting status/severity should produce 0 alerts", 0, alerted);
        assertFalse(preferences.isIncidentAlerted("inc-003"));
        assertFalse(preferences.isIncidentAlerted("inc-004"));
        assertFalse(preferences.isIncidentAlerted("inc-005"));
        assertFalse(preferences.isIncidentAlerted("inc-006"));
    }

    @Test
    public void testBoundedAlertedIdPersistence() {
        // Add 150 incident IDs
        for (int i = 1; i <= 150; i++) {
            preferences.addAlertedIncidentId("inc-" + i);
        }

        Set<String> stored = preferences.getAlertedIncidentIds();
        assertTrue("Stored alerted IDs must not exceed MAX_ALERTED_IDS (100)", stored.size() <= AppPreferences.MAX_ALERTED_IDS);
        assertEquals("Stored alerted IDs should be capped exactly at 100", 100, stored.size());
    }

    @Test
    public void testNotificationConstantsAndIntentPayloadContract() {
        assertEquals("incident_id", IncidentPollingWorker.EXTRA_INCIDENT_ID);
        assertEquals("project_id", IncidentPollingWorker.EXTRA_PROJECT_ID);

        IncidentDTO incident = createIncident("inc-tap-test", "order-service", "open", "high");
        assertNotNull(incident);
        assertEquals("inc-tap-test", incident.id);
        assertEquals("order-service", incident.projectId);
    }
}
