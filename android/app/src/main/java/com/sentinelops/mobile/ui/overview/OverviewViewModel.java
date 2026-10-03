package com.sentinelops.mobile.ui.overview;

import android.app.Application;
import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import com.sentinelops.mobile.data.remote.model.*;
import com.sentinelops.mobile.data.repository.BackendHealthRepository;
import com.sentinelops.mobile.di.ServiceLocator;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import retrofit2.Response;

public class OverviewViewModel extends AndroidViewModel {

    public static class OverviewData {
        public ProjectDTO project;
        public int activeIncidentsCount = 0;
        public int healthyConnectorsCount = 0;
        public int degradedConnectorsCount = 0;
        public int unreadNotificationsCount = 0;
        public String errorMessage = null;
    }

    private final ApiClientFactory apiClientFactory;
    private final BackendHealthRepository healthRepository;
    private final MutableLiveData<OverviewData> overviewData = new MutableLiveData<>();
    private final MutableLiveData<Boolean> isLoading = new MutableLiveData<>(false);
    private final ExecutorService executor = Executors.newFixedThreadPool(2);

    private long requestSequence = 0;
    private String currentRequestedProjectId = null;

    public OverviewViewModel(@NonNull Application application) {
        super(application);
        ServiceLocator locator = ServiceLocator.getInstance(application);
        this.apiClientFactory = locator.getApiClientFactory();
        this.healthRepository = locator.getBackendHealthRepository();
    }

    public LiveData<OverviewData> getOverviewData() {
        return overviewData;
    }

    public LiveData<Boolean> getIsLoading() {
        return isLoading;
    }

    public synchronized void refresh(String projectId) {
        if (projectId == null) return;
        final long requestId = ++requestSequence;
        this.currentRequestedProjectId = projectId;

        isLoading.setValue(true);
        executor.execute(() -> {
            OverviewData data = new OverviewData();
            try {
                // 1. Project details
                Response<ProjectDTO> projResp = apiClientFactory.getApi().getProject(projectId).execute();
                if (projResp.isSuccessful() && projResp.body() != null) {
                    data.project = projResp.body();
                    healthRepository.setOnline(true);
                }

                // 2. Incidents
                Response<List<IncidentDTO>> incResp = apiClientFactory.getApi().listIncidents().execute();
                if (incResp.isSuccessful() && incResp.body() != null) {
                    int count = 0;
                    for (IncidentDTO inc : incResp.body()) {
                        if (projectId.equals(inc.projectId)) {
                            if ("open".equalsIgnoreCase(inc.status) || "investigating".equalsIgnoreCase(inc.status)) {
                                count++;
                            }
                        }
                    }
                    data.activeIncidentsCount = count;
                }

                // 3. Connectors
                Response<List<ConnectorResponseDTO>> connResp = apiClientFactory.getApi().listConnectors(projectId).execute();
                if (connResp.isSuccessful() && connResp.body() != null) {
                    for (ConnectorResponseDTO c : connResp.body()) {
                        if (c.health != null) {
                            if ("healthy".equalsIgnoreCase(c.health.operationalStatus)) {
                                data.healthyConnectorsCount++;
                            } else {
                                data.degradedConnectorsCount++;
                            }
                        } else {
                            data.healthyConnectorsCount++;
                        }
                    }
                }

                // 4. Notifications (Unread in loaded batch)
                Response<List<NotificationResponseDTO>> notifResp = apiClientFactory.getApi()
                    .listNotifications(projectId, "unread", null, null, 50, 0)
                    .execute();
                if (notifResp.isSuccessful() && notifResp.body() != null) {
                    data.unreadNotificationsCount = notifResp.body().size();
                }

            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                data.errorMessage = "Failed to load overview: " + e.getMessage();
            } finally {
                // Stale response guard: reject if user switched projects while request was in-flight
                synchronized (OverviewViewModel.this) {
                    if (requestId == requestSequence && projectId.equals(currentRequestedProjectId)) {
                        overviewData.postValue(data);
                        isLoading.postValue(false);
                    }
                }
            }
        });
    }
}
