package com.sentinelops.mobile.di;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.lifecycle.DefaultLifecycleObserver;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.ProcessLifecycleOwner;
import com.sentinelops.mobile.data.local.AppPreferences;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import com.sentinelops.mobile.data.repository.*;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

public class ServiceLocator {

    private static volatile ServiceLocator INSTANCE;

    private final AppPreferences appPreferences;
    private final ApiClientFactory apiClientFactory;
    private final BackendHealthRepository backendHealthRepository;
    private final ProjectRepository projectRepository;
    private final IncidentRepository incidentRepository;
    private final ConnectorRepository connectorRepository;
    private final NotificationRepository notificationRepository;

    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();
    private ScheduledFuture<?> pollingTask;
    private boolean isAppInForeground = false;

    private ServiceLocator(Context context) {
        this.appPreferences = new AppPreferences(context.getApplicationContext());
        this.apiClientFactory = new ApiClientFactory(appPreferences.getBackendUrl());
        this.backendHealthRepository = new BackendHealthRepository(apiClientFactory);
        this.projectRepository = new ProjectRepository(apiClientFactory, backendHealthRepository);
        this.incidentRepository = new IncidentRepository(apiClientFactory, backendHealthRepository);
        this.connectorRepository = new ConnectorRepository(apiClientFactory, backendHealthRepository);
        this.notificationRepository = new NotificationRepository(apiClientFactory, backendHealthRepository);

        initLifecyclePolling();
    }

    public static ServiceLocator getInstance(Context context) {
        if (INSTANCE == null) {
            synchronized (ServiceLocator.class) {
                if (INSTANCE == null) {
                    INSTANCE = new ServiceLocator(context);
                }
            }
        }
        return INSTANCE;
    }

    private void initLifecyclePolling() {
        ProcessLifecycleOwner.get().getLifecycle().addObserver(new DefaultLifecycleObserver() {
            @Override
            public void onStart(@NonNull LifecycleOwner owner) {
                isAppInForeground = true;
                startForegroundPolling();
            }

            @Override
            public void onStop(@NonNull LifecycleOwner owner) {
                isAppInForeground = false;
                stopForegroundPolling();
            }
        });
    }

    public synchronized void startForegroundPolling() {
        stopForegroundPolling();
        int intervalSeconds = appPreferences.getPollingIntervalSeconds();
        if (intervalSeconds <= 0 || !isAppInForeground) {
            return; // Manual only or backgrounded
        }
        pollingTask = scheduler.scheduleWithFixedDelay(
            () -> backendHealthRepository.probeHealthAsync(null),
            intervalSeconds,
            intervalSeconds,
            TimeUnit.SECONDS
        );
    }

    public synchronized void stopForegroundPolling() {
        if (pollingTask != null) {
            pollingTask.cancel(true);
            pollingTask = null;
        }
    }

    public void updateBackendUrl(String newUrl) {
        appPreferences.setBackendUrl(newUrl);
        apiClientFactory.updateBaseUrl(newUrl);
        backendHealthRepository.probeHealthAsync(null);
    }

    public AppPreferences getAppPreferences() {
        return appPreferences;
    }

    public ApiClientFactory getApiClientFactory() {
        return apiClientFactory;
    }

    public BackendHealthRepository getBackendHealthRepository() {
        return backendHealthRepository;
    }

    public ProjectRepository getProjectRepository() {
        return projectRepository;
    }

    public IncidentRepository getIncidentRepository() {
        return incidentRepository;
    }

    public ConnectorRepository getConnectorRepository() {
        return connectorRepository;
    }

    public NotificationRepository getNotificationRepository() {
        return notificationRepository;
    }
}
