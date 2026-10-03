package com.sentinelops.mobile.ui.incidents;

import android.app.Application;
import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.model.*;
import com.sentinelops.mobile.data.repository.IncidentRepository;
import com.sentinelops.mobile.di.ServiceLocator;
import com.sentinelops.mobile.ui.common.Resource;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class IncidentViewModel extends AndroidViewModel {

    private final IncidentRepository incidentRepository;
    private final Set<String> inFlightOperations = Collections.synchronizedSet(new HashSet<>());

    private final MutableLiveData<List<IncidentDTO>> allIncidents = new MutableLiveData<>(new ArrayList<>());
    private final MutableLiveData<List<IncidentDTO>> filteredIncidents = new MutableLiveData<>(new ArrayList<>());
    private final MutableLiveData<Boolean> isLoading = new MutableLiveData<>(false);
    private final MutableLiveData<String> errorMessage = new MutableLiveData<>(null);

    // Detail state
    private final MutableLiveData<IncidentDTO> incidentDetail = new MutableLiveData<>();
    private final MutableLiveData<List<EvidenceDTO>> evidenceList = new MutableLiveData<>(new ArrayList<>());
    private final MutableLiveData<InvestigationResponseDTO> investigation = new MutableLiveData<>(null);
    private final MutableLiveData<RemediationProposalResponseDTO> remediation = new MutableLiveData<>(null);
    private final MutableLiveData<Boolean> isDetailLoading = new MutableLiveData<>(false);
    private final MutableLiveData<Boolean> isTransitioning = new MutableLiveData<>(false);
    private final MutableLiveData<String> transitionError = new MutableLiveData<>(null);

    private String currentSeverityFilter = "All";
    private String currentStatusFilter = "All";

    private long requestSequence = 0;
    private String currentRequestedProjectId = null;

    public IncidentViewModel(@NonNull Application application) {
        super(application);
        this.incidentRepository = ServiceLocator.getInstance(application).getIncidentRepository();
    }

    public LiveData<List<IncidentDTO>> getFilteredIncidents() {
        return filteredIncidents;
    }

    public LiveData<Boolean> getIsLoading() {
        return isLoading;
    }

    public LiveData<String> getErrorMessage() {
        return errorMessage;
    }

    public LiveData<IncidentDTO> getIncidentDetail() {
        return incidentDetail;
    }

    public LiveData<List<EvidenceDTO>> getEvidenceList() {
        return evidenceList;
    }

    public LiveData<InvestigationResponseDTO> getInvestigation() {
        return investigation;
    }

    public LiveData<RemediationProposalResponseDTO> getRemediation() {
        return remediation;
    }

    public LiveData<Boolean> getIsDetailLoading() {
        return isDetailLoading;
    }

    public LiveData<Boolean> getIsTransitioning() {
        return isTransitioning;
    }

    public LiveData<String> getTransitionError() {
        return transitionError;
    }

    public synchronized void loadIncidents(String projectId) {
        if (projectId == null) {
            allIncidents.setValue(new ArrayList<>());
            filteredIncidents.setValue(new ArrayList<>());
            isLoading.setValue(false);
            return;
        }

        final long requestId = ++requestSequence;
        this.currentRequestedProjectId = projectId;

        isLoading.setValue(true);
        errorMessage.setValue(null);

        incidentRepository.listIncidents().observeForever(resource -> {
            if (resource == null) return;

            // Stale response guard
            synchronized (IncidentViewModel.this) {
                if (requestId != requestSequence || !projectId.equals(currentRequestedProjectId)) {
                    return; // Stale response dropped
                }
            }

            if (resource.isLoading()) {
                isLoading.postValue(true);
            } else if (resource.isSuccess() && resource.data != null) {
                isLoading.postValue(false);
                List<IncidentDTO> projectIncidents = new ArrayList<>();
                for (IncidentDTO inc : resource.data) {
                    if (projectId.equals(inc.projectId)) {
                        projectIncidents.add(inc);
                    }
                }
                allIncidents.postValue(projectIncidents);
                applyFilters(projectIncidents, currentSeverityFilter, currentStatusFilter);
            } else {
                isLoading.postValue(false);
                errorMessage.postValue(resource.message);
            }
        });
    }

    public void setSeverityFilter(String severity) {
        this.currentSeverityFilter = severity;
        applyFilters(allIncidents.getValue(), currentSeverityFilter, currentStatusFilter);
    }

    public void setStatusFilter(String status) {
        this.currentStatusFilter = status;
        applyFilters(allIncidents.getValue(), currentSeverityFilter, currentStatusFilter);
    }

    private void applyFilters(List<IncidentDTO> list, String severity, String status) {
        if (list == null) {
            filteredIncidents.postValue(new ArrayList<>());
            return;
        }
        List<IncidentDTO> result = new ArrayList<>();
        for (IncidentDTO item : list) {
            boolean matchesSeverity = "All".equalsIgnoreCase(severity) ||
                (item.severity != null && item.severity.equalsIgnoreCase(severity));
            boolean matchesStatus = "All".equalsIgnoreCase(status) ||
                (item.status != null && item.status.equalsIgnoreCase(status));

            if (matchesSeverity && matchesStatus) {
                result.add(item);
            }
        }
        filteredIncidents.postValue(result);
    }

    public void loadIncidentDetail(String incidentId) {
        isDetailLoading.setValue(true);
        transitionError.setValue(null);

        // Load metadata
        incidentRepository.getIncident(incidentId).observeForever(resource -> {
            if (resource != null && resource.isSuccess()) {
                incidentDetail.postValue(resource.data);
            }
        });

        // Load evidence
        incidentRepository.listEvidence(incidentId).observeForever(resource -> {
            if (resource != null && resource.isSuccess() && resource.data != null) {
                evidenceList.postValue(resource.data);
            }
        });

        // Load investigation
        incidentRepository.getInvestigation(incidentId).observeForever(resource -> {
            if (resource != null && resource.isSuccess()) {
                investigation.postValue(resource.data);
            }
        });

        // Load remediation
        incidentRepository.getRemediation(incidentId).observeForever(resource -> {
            isDetailLoading.postValue(false);
            if (resource != null && resource.isSuccess()) {
                remediation.postValue(resource.data);
            }
        });
    }

    public void transitionIncidentStatus(String incidentId, String targetStatus) {
        String operationKey = incidentId + ":" + targetStatus;
        if (inFlightOperations.contains(operationKey)) {
            return; // Duplicate action guard
        }
        inFlightOperations.add(operationKey);
        isTransitioning.setValue(true);
        transitionError.setValue(null);

        incidentRepository.updateIncidentStatus(incidentId, targetStatus).observeForever(resource -> {
            if (resource == null) return;
            if (resource.isSuccess() && resource.data != null) {
                inFlightOperations.remove(operationKey);
                isTransitioning.postValue(false);
                incidentDetail.postValue(resource.data); // Authoritative server response
            } else if (resource.isError()) {
                inFlightOperations.remove(operationKey);
                isTransitioning.postValue(false);
                transitionError.postValue(resource.message);
            }
        });
    }
}
