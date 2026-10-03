package com.sentinelops.mobile.data.repository;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import com.sentinelops.mobile.data.remote.model.MarkAllReadResponseDTO;
import com.sentinelops.mobile.data.remote.model.NotificationResponseDTO;
import com.sentinelops.mobile.ui.common.Resource;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import retrofit2.Response;

public class NotificationRepository {

    private final ApiClientFactory apiClientFactory;
    private final BackendHealthRepository healthRepository;
    private final ExecutorService executor = Executors.newFixedThreadPool(3);

    public NotificationRepository(ApiClientFactory apiClientFactory, BackendHealthRepository healthRepository) {
        this.apiClientFactory = apiClientFactory;
        this.healthRepository = healthRepository;
    }

    public LiveData<Resource<List<NotificationResponseDTO>>> listNotifications(
        String projectId,
        String readStatus,
        int limit,
        int offset
    ) {
        MutableLiveData<Resource<List<NotificationResponseDTO>>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<List<NotificationResponseDTO>> response = apiClientFactory.getApi()
                    .listNotifications(projectId, readStatus, null, null, limit, offset)
                    .execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Failed to load notifications: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<NotificationResponseDTO>> markRead(String notificationId) {
        MutableLiveData<Resource<NotificationResponseDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<NotificationResponseDTO> response = apiClientFactory.getApi()
                    .markNotificationRead(notificationId)
                    .execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Failed to mark as read: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<MarkAllReadResponseDTO>> markAllRead(String projectId) {
        MutableLiveData<Resource<MarkAllReadResponseDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<MarkAllReadResponseDTO> response = apiClientFactory.getApi()
                    .markAllNotificationsRead(projectId)
                    .execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Failed to mark all as read: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<NotificationResponseDTO>> retryNotification(String notificationId) {
        MutableLiveData<Resource<NotificationResponseDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<NotificationResponseDTO> response = apiClientFactory.getApi()
                    .retryNotification(notificationId)
                    .execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Retry failed: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }
}
