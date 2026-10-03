package com.sentinelops.mobile.ui.settings;

import android.app.Application;
import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.local.AppPreferences;
import com.sentinelops.mobile.data.repository.BackendHealthRepository;
import com.sentinelops.mobile.di.ServiceLocator;

public class SettingsViewModel extends AndroidViewModel {

    private final ServiceLocator serviceLocator;
    private final AppPreferences appPreferences;
    private final BackendHealthRepository healthRepository;

    private final MutableLiveData<String> backendUrl = new MutableLiveData<>();
    private final MutableLiveData<Integer> pollingInterval = new MutableLiveData<>();
    private final MutableLiveData<String> testResult = new MutableLiveData<>(null);
    private final MutableLiveData<Boolean> isTesting = new MutableLiveData<>(false);

    public SettingsViewModel(@NonNull Application application) {
        super(application);
        this.serviceLocator = ServiceLocator.getInstance(application);
        this.appPreferences = serviceLocator.getAppPreferences();
        this.healthRepository = serviceLocator.getBackendHealthRepository();

        this.backendUrl.setValue(appPreferences.getBackendUrl());
        this.pollingInterval.setValue(appPreferences.getPollingIntervalSeconds());
    }

    public LiveData<String> getBackendUrl() {
        return backendUrl;
    }

    public LiveData<Integer> getPollingInterval() {
        return pollingInterval;
    }

    public LiveData<String> getTestResult() {
        return testResult;
    }

    public LiveData<Boolean> getIsTesting() {
        return isTesting;
    }

    public void testConnection(String url) {
        isTesting.setValue(true);
        testResult.setValue(null);

        // Temporarily or permanently update base URL
        serviceLocator.updateBackendUrl(url);
        backendUrl.setValue(url);

        healthRepository.probeHealthAsync((healthy, statusCode, latencyMs, message) -> {
            isTesting.postValue(false);
            if (healthy) {
                testResult.postValue("Connected successfully: HTTP " + statusCode +
                    " (" + latencyMs + " ms) - " + message);
            } else {
                testResult.postValue("Connection failed: " + message);
            }
        });
    }

    public void setPollingInterval(int seconds) {
        appPreferences.setPollingIntervalSeconds(seconds);
        pollingInterval.setValue(seconds);
        serviceLocator.startForegroundPolling();
    }
}
