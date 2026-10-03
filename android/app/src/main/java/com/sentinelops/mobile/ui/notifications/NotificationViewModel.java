package com.sentinelops.mobile.ui.notifications;

import android.app.Application;
import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.model.NotificationResponseDTO;
import com.sentinelops.mobile.data.repository.NotificationRepository;
import com.sentinelops.mobile.di.ServiceLocator;
import com.sentinelops.mobile.ui.common.Resource;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class NotificationViewModel extends AndroidViewModel {

    private final NotificationRepository notificationRepository;
    private final Set<String> inFlightActions = Collections.synchronizedSet(new HashSet<>());

    private final MutableLiveData<List<NotificationResponseDTO>> allNotifications = new MutableLiveData<>(new ArrayList<>());
    private final MutableLiveData<List<NotificationResponseDTO>> displayedNotifications = new MutableLiveData<>(new ArrayList<>());
    private final MutableLiveData<Integer> batchUnreadCount = new MutableLiveData<>(0);
    private final MutableLiveData<Boolean> isLoading = new MutableLiveData<>(false);
    private final MutableLiveData<String> actionInFlightId = new MutableLiveData<>(null);
    private final MutableLiveData<String> feedbackMessage = new MutableLiveData<>(null);

    private boolean unreadOnlyFilter = false;
    private String currentProjectId = "default";

    public NotificationViewModel(@NonNull Application application) {
        super(application);
        this.notificationRepository = ServiceLocator.getInstance(application).getNotificationRepository();
    }

    public LiveData<List<NotificationResponseDTO>> getDisplayedNotifications() {
        return displayedNotifications;
    }

    public LiveData<Integer> getBatchUnreadCount() {
        return batchUnreadCount;
    }

    public LiveData<Boolean> getIsLoading() {
        return isLoading;
    }

    public LiveData<String> getActionInFlightId() {
        return actionInFlightId;
    }

    public LiveData<String> getFeedbackMessage() {
        return feedbackMessage;
    }

    private long requestSequence = 0;
    private String currentRequestedProjectId = null;

    public synchronized void loadNotifications(String projectId) {
        this.currentProjectId = projectId;
        if (projectId == null) {
            allNotifications.setValue(new ArrayList<>());
            displayedNotifications.setValue(new ArrayList<>());
            batchUnreadCount.setValue(0);
            isLoading.setValue(false);
            return;
        }

        final long requestId = ++requestSequence;
        this.currentRequestedProjectId = projectId;

        isLoading.setValue(true);
        notificationRepository.listNotifications(projectId, null, 50, 0).observeForever(resource -> {
            if (resource == null) return;

            // Stale response guard
            synchronized (NotificationViewModel.this) {
                if (requestId != requestSequence || !projectId.equals(currentRequestedProjectId)) {
                    return; // Stale response dropped
                }
            }

            if (resource.isLoading()) {
                isLoading.postValue(true);
            } else if (resource.isSuccess() && resource.data != null) {
                isLoading.postValue(false);
                allNotifications.postValue(resource.data);

                // Compute unread in loaded batch
                int unread = 0;
                for (NotificationResponseDTO n : resource.data) {
                    if ("unread".equalsIgnoreCase(n.readStatus)) {
                        unread++;
                    }
                }
                batchUnreadCount.postValue(unread);
                applyFilter(resource.data, unreadOnlyFilter);
            } else {
                isLoading.postValue(false);
                feedbackMessage.postValue(resource.message);
            }
        });
    }

    public void setUnreadOnlyFilter(boolean unreadOnly) {
        this.unreadOnlyFilter = unreadOnly;
        applyFilter(allNotifications.getValue(), unreadOnlyFilter);
    }

    private void applyFilter(List<NotificationResponseDTO> list, boolean unreadOnly) {
        if (list == null) {
            displayedNotifications.postValue(new ArrayList<>());
            return;
        }
        if (!unreadOnly) {
            displayedNotifications.postValue(list);
            return;
        }
        List<NotificationResponseDTO> filtered = new ArrayList<>();
        for (NotificationResponseDTO item : list) {
            if ("unread".equalsIgnoreCase(item.readStatus)) {
                filtered.add(item);
            }
        }
        displayedNotifications.postValue(filtered);
    }

    public void markRead(String notificationId) {
        if (inFlightActions.contains(notificationId)) {
            return; // Duplicate action guard
        }
        inFlightActions.add(notificationId);
        actionInFlightId.setValue(notificationId);

        notificationRepository.markRead(notificationId).observeForever(resource -> {
            if (resource == null) return;
            if (resource.isSuccess() && resource.data != null) {
                inFlightActions.remove(notificationId);
                actionInFlightId.postValue(null);
                loadNotifications(currentProjectId); // Server-confirmed reload
            } else if (resource.isError()) {
                inFlightActions.remove(notificationId);
                actionInFlightId.postValue(null);
                feedbackMessage.postValue("Mark read failed: " + resource.message);
            }
        });
    }

    public void markAllRead() {
        isLoading.setValue(true);
        notificationRepository.markAllRead(currentProjectId).observeForever(resource -> {
            if (resource == null) return;
            if (resource.isSuccess()) {
                feedbackMessage.postValue("All notifications marked as read.");
                loadNotifications(currentProjectId); // Server-confirmed reload
            } else if (resource.isError()) {
                isLoading.postValue(false);
                feedbackMessage.postValue("Failed to mark all read: " + resource.message);
            }
        });
    }

    public void retryNotification(String notificationId) {
        if (inFlightActions.contains(notificationId)) {
            return; // Duplicate retry guard
        }
        inFlightActions.add(notificationId);
        actionInFlightId.setValue(notificationId);

        notificationRepository.retryNotification(notificationId).observeForever(resource -> {
            if (resource == null) return;
            if (resource.isSuccess()) {
                inFlightActions.remove(notificationId);
                actionInFlightId.postValue(null);
                feedbackMessage.postValue("Retry dispatched.");
                loadNotifications(currentProjectId);
            } else if (resource.isError()) {
                inFlightActions.remove(notificationId);
                actionInFlightId.postValue(null);
                feedbackMessage.postValue("Retry failed: " + resource.message);
            }
        });
    }
}
