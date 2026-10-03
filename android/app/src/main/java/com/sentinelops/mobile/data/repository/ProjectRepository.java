package com.sentinelops.mobile.data.repository;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import com.sentinelops.mobile.data.remote.model.ProjectDTO;
import com.sentinelops.mobile.ui.common.Resource;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import retrofit2.Response;

public class ProjectRepository {

    private final ApiClientFactory apiClientFactory;
    private final BackendHealthRepository healthRepository;
    private final ExecutorService executor = Executors.newFixedThreadPool(2);

    public ProjectRepository(ApiClientFactory apiClientFactory, BackendHealthRepository healthRepository) {
        this.apiClientFactory = apiClientFactory;
        this.healthRepository = healthRepository;
    }

    public LiveData<Resource<List<ProjectDTO>>> listProjects() {
        MutableLiveData<Resource<List<ProjectDTO>>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<List<ProjectDTO>> response = apiClientFactory.getApi().listProjects().execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Failed to load projects: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<ProjectDTO>> getProject(String projectId) {
        MutableLiveData<Resource<ProjectDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<ProjectDTO> response = apiClientFactory.getApi().getProject(projectId).execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Project not found: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }
}
