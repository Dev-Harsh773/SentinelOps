package com.sentinelops.mobile.ui.connectors;

import android.app.Application;
import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.model.ConnectorResponseDTO;
import com.sentinelops.mobile.data.remote.model.ConnectorTestResultDTO;
import com.sentinelops.mobile.data.repository.ConnectorRepository;
import com.sentinelops.mobile.di.ServiceLocator;
import com.sentinelops.mobile.ui.common.Resource;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class ConnectorViewModel extends AndroidViewModel {

    private final ConnectorRepository connectorRepository;
    private final Set<String> inFlightTests = Collections.synchronizedSet(new HashSet<>());

    private final MutableLiveData<List<ConnectorResponseDTO>> connectorsList = new MutableLiveData<>(new ArrayList<>());
    private final MutableLiveData<Boolean> isLoading = new MutableLiveData<>(false);
    private final MutableLiveData<String> errorMessage = new MutableLiveData<>(null);
    private final MutableLiveData<String> testResultMessage = new MutableLiveData<>(null);
    private final MutableLiveData<String> testingConnectorId = new MutableLiveData<>(null);

    public ConnectorViewModel(@NonNull Application application) {
        super(application);
        this.connectorRepository = ServiceLocator.getInstance(application).getConnectorRepository();
    }

    public LiveData<List<ConnectorResponseDTO>> getConnectorsList() {
        return connectorsList;
    }

    public LiveData<Boolean> getIsLoading() {
        return isLoading;
    }

    public LiveData<String> getErrorMessage() {
        return errorMessage;
    }

    public LiveData<String> getTestResultMessage() {
        return testResultMessage;
    }

    public LiveData<String> getTestingConnectorId() {
        return testingConnectorId;
    }

    private long requestSequence = 0;
    private String currentRequestedProjectId = null;

    public synchronized void loadConnectors(String projectId) {
        if (projectId == null) {
            connectorsList.setValue(new ArrayList<>());
            isLoading.setValue(false);
            return;
        }

        final long requestId = ++requestSequence;
        this.currentRequestedProjectId = projectId;

        isLoading.setValue(true);
        errorMessage.setValue(null);
        connectorRepository.listConnectors(projectId).observeForever(resource -> {
            if (resource == null) return;

            // Stale response guard
            synchronized (ConnectorViewModel.this) {
                if (requestId != requestSequence || !projectId.equals(currentRequestedProjectId)) {
                    return; // Stale response dropped
                }
            }

            if (resource.isLoading()) {
                isLoading.postValue(true);
            } else if (resource.isSuccess() && resource.data != null) {
                isLoading.postValue(false);
                connectorsList.postValue(resource.data);
            } else {
                isLoading.postValue(false);
                errorMessage.postValue(resource.message);
            }
        });
    }

    public void testConnector(String connectorId) {
        if (inFlightTests.contains(connectorId)) {
            return; // Duplicate test guard
        }
        inFlightTests.add(connectorId);
        testingConnectorId.setValue(connectorId);

        connectorRepository.testConnector(connectorId).observeForever(resource -> {
            if (resource == null) return;
            if (resource.isSuccess() && resource.data != null) {
                inFlightTests.remove(connectorId);
                testingConnectorId.postValue(null);
                ConnectorTestResultDTO result = resource.data;
                String msg = "Test Result: " + result.status.toUpperCase() +
                    (result.statusCode != null ? " (HTTP " + result.statusCode + ")" : "") +
                    (result.latencyMs != null ? " [" + result.latencyMs + " ms]" : "");
                testResultMessage.postValue(msg);
            } else if (resource.isError()) {
                inFlightTests.remove(connectorId);
                testingConnectorId.postValue(null);
                testResultMessage.postValue("Test Failed: " + resource.message);
            }
        });
    }
}
