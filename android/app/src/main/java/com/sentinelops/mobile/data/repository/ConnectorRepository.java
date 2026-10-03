package com.sentinelops.mobile.data.repository;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import com.sentinelops.mobile.data.remote.model.ConnectorResponseDTO;
import com.sentinelops.mobile.data.remote.model.ConnectorTestResultDTO;
import com.sentinelops.mobile.ui.common.Resource;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import retrofit2.Response;

public class ConnectorRepository {

    private final ApiClientFactory apiClientFactory;
    private final BackendHealthRepository healthRepository;
    private final ExecutorService executor = Executors.newFixedThreadPool(2);

    public ConnectorRepository(ApiClientFactory apiClientFactory, BackendHealthRepository healthRepository) {
        this.apiClientFactory = apiClientFactory;
        this.healthRepository = healthRepository;
    }

    public LiveData<Resource<List<ConnectorResponseDTO>>> listConnectors(String projectId) {
        MutableLiveData<Resource<List<ConnectorResponseDTO>>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<List<ConnectorResponseDTO>> response = apiClientFactory.getApi().listConnectors(projectId).execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Failed to load connectors: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<ConnectorTestResultDTO>> testConnector(String connectorId) {
        MutableLiveData<Resource<ConnectorTestResultDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<ConnectorTestResultDTO> response = apiClientFactory.getApi().testConnector(connectorId).execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Connector test failed: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }
}
