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

    public int getPollingIntervalSeconds() {
        return prefs.getInt(KEY_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL);
    }

    public void setPollingIntervalSeconds(int seconds) {
        prefs.edit().putInt(KEY_POLLING_INTERVAL, seconds).apply();
    }
}
