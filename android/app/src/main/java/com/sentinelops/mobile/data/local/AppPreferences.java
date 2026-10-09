package com.sentinelops.mobile.data.local;

import android.content.Context;
import android.content.SharedPreferences;

public class AppPreferences {
    private static final String PREF_NAME = "sentinelops_mobile_prefs";
    private static final String KEY_BACKEND_URL = "key_backend_url";
    private static final String KEY_ACTIVE_PROJECT_ID = "key_active_project_id";
    private static final String KEY_POLLING_INTERVAL = "key_polling_interval";

    public static final String DEFAULT_BACKEND_URL = "http://10.0.2.2:8000";
    public static final int DEFAULT_POLLING_INTERVAL = 30; // seconds

    private final SharedPreferences prefs;

    public AppPreferences(Context context) {
        this.prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
    }

    public String getBackendUrl() {
        return prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL);
    }

    public void setBackendUrl(String url) {
        prefs.edit().putString(KEY_BACKEND_URL, url.trim()).apply();
    }

    public String getSavedProjectId() {
        return prefs.getString(KEY_ACTIVE_PROJECT_ID, null);
    }

    public String getActiveProjectId() {
        return getSavedProjectId();
    }

    public void setActiveProjectId(String projectId) {
        if (projectId == null) {
            prefs.edit().remove(KEY_ACTIVE_PROJECT_ID).apply();
        } else {
            prefs.edit().putString(KEY_ACTIVE_PROJECT_ID, projectId).apply();
        }
    }

    private static final String KEY_ALERTED_INCIDENT_IDS = "key_alerted_incident_ids";
    public static final int MAX_ALERTED_IDS = 100;

    public java.util.Set<String> getAlertedIncidentIds() {
        java.util.Set<String> set = prefs.getStringSet(KEY_ALERTED_INCIDENT_IDS, null);
        return set != null ? new java.util.HashSet<>(set) : new java.util.HashSet<>();
    }

    public void addAlertedIncidentId(String incidentId) {
        if (incidentId == null || incidentId.trim().isEmpty()) return;
        java.util.Set<String> current = getAlertedIncidentIds();
        current.add(incidentId.trim());
        if (current.size() > MAX_ALERTED_IDS) {
            java.util.List<String> list = new java.util.ArrayList<>(current);
            current = new java.util.HashSet<>(list.subList(list.size() - MAX_ALERTED_IDS, list.size()));
        }
        prefs.edit().putStringSet(KEY_ALERTED_INCIDENT_IDS, current).apply();
    }

    public boolean isIncidentAlerted(String incidentId) {
        if (incidentId == null) return false;
        return getAlertedIncidentIds().contains(incidentId.trim());
    }

    public int getPollingIntervalSeconds() {
        return prefs.getInt(KEY_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL);
    }

    public void setPollingIntervalSeconds(int seconds) {
        prefs.edit().putInt(KEY_POLLING_INTERVAL, seconds).apply();
    }
}
