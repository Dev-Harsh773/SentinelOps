package com.sentinelops.mobile.data.repository;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import com.sentinelops.mobile.data.remote.model.*;
import com.sentinelops.mobile.ui.common.Resource;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import retrofit2.Response;

public class IncidentRepository {

    private final ApiClientFactory apiClientFactory;
    private final BackendHealthRepository healthRepository;
    private final ExecutorService executor = Executors.newFixedThreadPool(3);

    public IncidentRepository(ApiClientFactory apiClientFactory, BackendHealthRepository healthRepository) {
        this.apiClientFactory = apiClientFactory;
        this.healthRepository = healthRepository;
    }

    public LiveData<Resource<List<IncidentDTO>>> listIncidents() {
        MutableLiveData<Resource<List<IncidentDTO>>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<List<IncidentDTO>> response = apiClientFactory.getApi().listIncidents().execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Failed to load incidents: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<IncidentDTO>> getIncident(String id) {
        MutableLiveData<Resource<IncidentDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<IncidentDTO> response = apiClientFactory.getApi().getIncident(id).execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Incident not found: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<IncidentDTO>> updateIncidentStatus(String id, String targetStatus) {
        MutableLiveData<Resource<IncidentDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                IncidentStatusUpdateRequestDTO payload = new IncidentStatusUpdateRequestDTO(targetStatus);
                Response<IncidentDTO> response = apiClientFactory.getApi().updateIncidentStatus(id, payload).execute();
                if (response.isSuccessful() && response.body() != null) {
                    healthRepository.setOnline(true);
                    result.postValue(Resource.success(response.body()));
                } else {
                    String errorDetail = "HTTP " + response.code();
                    try {
                        if (response.errorBody() != null) {
                            errorDetail += " - " + response.errorBody().string();
                        }
                    } catch (Exception ignored) {}
                    result.postValue(Resource.error("Transition failed: " + errorDetail, null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<List<EvidenceDTO>>> listEvidence(String incidentId) {
        MutableLiveData<Resource<List<EvidenceDTO>>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<List<EvidenceDTO>> response = apiClientFactory.getApi().listIncidentEvidence(incidentId).execute();
                if (response.isSuccessful() && response.body() != null) {
                    result.postValue(Resource.success(response.body()));
                } else {
                    result.postValue(Resource.error("Failed to load evidence: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<InvestigationResponseDTO>> getInvestigation(String incidentId) {
        MutableLiveData<Resource<InvestigationResponseDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<InvestigationResponseDTO> response = apiClientFactory.getApi().getIncidentInvestigation(incidentId).execute();
                if (response.isSuccessful() && response.body() != null) {
                    result.postValue(Resource.success(response.body()));
                } else if (response.code() == 404) {
                    result.postValue(Resource.success(null)); // Not yet investigated
                } else {
                    result.postValue(Resource.error("Investigation lookup error: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }

    public LiveData<Resource<RemediationProposalResponseDTO>> getRemediation(String incidentId) {
        MutableLiveData<Resource<RemediationProposalResponseDTO>> result = new MutableLiveData<>(Resource.loading(null));
        executor.execute(() -> {
            try {
                Response<RemediationProposalResponseDTO> response = apiClientFactory.getApi().getIncidentRemediation(incidentId).execute();
                if (response.isSuccessful() && response.body() != null) {
                    result.postValue(Resource.success(response.body()));
                } else if (response.code() == 404) {
                    result.postValue(Resource.success(null)); // No proposal yet
                } else {
                    result.postValue(Resource.error("Remediation lookup error: HTTP " + response.code(), null));
                }
            } catch (IOException e) {
                healthRepository.handleTransportError(e);
                result.postValue(Resource.error("Network error: " + e.getMessage(), null));
            }
        });
        return result;
    }
}
