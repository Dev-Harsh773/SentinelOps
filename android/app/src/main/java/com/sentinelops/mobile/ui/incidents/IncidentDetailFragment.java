package com.sentinelops.mobile.ui.incidents;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.LinearLayoutManager;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.data.remote.model.IncidentDTO;
import com.sentinelops.mobile.databinding.FragmentIncidentDetailBinding;
import com.sentinelops.mobile.ui.common.DateFormatHelper;
import com.sentinelops.mobile.ui.common.StatusBadgeHelper;
import com.sentinelops.mobile.ui.incidents.adapter.EvidenceAdapter;
import com.sentinelops.mobile.ui.incidents.adapter.ProposedChangeAdapter;
import com.sentinelops.mobile.ui.main.MainViewModel;

public class IncidentDetailFragment extends Fragment {

    private FragmentIncidentDetailBinding binding;
    private IncidentViewModel incidentViewModel;
    private MainViewModel mainViewModel;

    private EvidenceAdapter evidenceAdapter;
    private ProposedChangeAdapter proposedChangeAdapter;
    private String incidentId;
    private boolean isBackendOnline = true;

    @Nullable
    @Override
    public View onCreateView(
        @NonNull LayoutInflater inflater,
        @Nullable ViewGroup container,
        @Nullable Bundle savedInstanceState
    ) {
        binding = FragmentIncidentDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        incidentViewModel = new ViewModelProvider(this).get(IncidentViewModel.class);
        mainViewModel = new ViewModelProvider(requireActivity()).get(MainViewModel.class);

        if (getArguments() != null) {
            incidentId = getArguments().getString("incident_id");
        }

        setupRecyclerViews();
        setupLifecycleActionButtons();

        binding.swipeRefresh.setOnRefreshListener(() -> {
            if (incidentId != null) {
                incidentViewModel.loadIncidentDetail(incidentId);
            } else {
                binding.swipeRefresh.setRefreshing(false);
            }
        });

        observeState();

        if (incidentId != null) {
            incidentViewModel.loadIncidentDetail(incidentId);
        }
    }

    private void setupRecyclerViews() {
        evidenceAdapter = new EvidenceAdapter();
        binding.recyclerEvidence.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.recyclerEvidence.setAdapter(evidenceAdapter);

        proposedChangeAdapter = new ProposedChangeAdapter();
        binding.recyclerProposedChanges.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.recyclerProposedChanges.setAdapter(proposedChangeAdapter);
    }

    private void setupLifecycleActionButtons() {
        binding.btnActionInvestigate.setOnClickListener(v -> {
            if (incidentId != null && isBackendOnline) {
                incidentViewModel.transitionIncidentStatus(incidentId, "investigating");
            }
        });

        binding.btnActionResolve.setOnClickListener(v -> {
            if (incidentId != null && isBackendOnline) {
                incidentViewModel.transitionIncidentStatus(incidentId, "resolved");
            }
        });

        binding.btnActionClose.setOnClickListener(v -> {
            if (incidentId != null && isBackendOnline) {
                incidentViewModel.transitionIncidentStatus(incidentId, "closed");
            }
        });
    }

    private void observeState() {
        mainViewModel.getIsOnline().observe(getViewLifecycleOwner(), online -> {
            if (binding == null) return;
            isBackendOnline = Boolean.TRUE.equals(online);
            updateButtonEnabledState();
        });

        incidentViewModel.getIsDetailLoading().observe(getViewLifecycleOwner(), loading -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(Boolean.TRUE.equals(loading));
        });

        incidentViewModel.getIsTransitioning().observe(getViewLifecycleOwner(), transitioning -> {
            if (binding == null) return;
            boolean inTransition = Boolean.TRUE.equals(transitioning);
            binding.progressLifecycle.setVisibility(inTransition ? View.VISIBLE : View.GONE);
            updateButtonEnabledState();
        });

        incidentViewModel.getTransitionError().observe(getViewLifecycleOwner(), error -> {
            if (binding == null) return;
            if (error != null) {
                Toast.makeText(requireContext(), error, Toast.LENGTH_LONG).show();
            }
        });

        incidentViewModel.getIncidentDetail().observe(getViewLifecycleOwner(), this::bindIncident);

        incidentViewModel.getEvidenceList().observe(getViewLifecycleOwner(), evidenceList -> {
            if (binding == null) return;
            evidenceAdapter.setItems(evidenceList);
            if (evidenceList == null || evidenceList.isEmpty()) {
                binding.tvNoEvidence.setVisibility(View.VISIBLE);
                binding.recyclerEvidence.setVisibility(View.GONE);
            } else {
                binding.tvNoEvidence.setVisibility(View.GONE);
                binding.recyclerEvidence.setVisibility(View.VISIBLE);
            }
        });

        incidentViewModel.getInvestigation().observe(getViewLifecycleOwner(), inv -> {
            if (binding == null) return;
            if (inv != null && inv.rca != null) {
                binding.tvNoInvestigation.setVisibility(View.GONE);
                int confPct = (int) Math.round(inv.rca.confidence * 100);
                binding.tvRcaConfidence.setText(getString(R.string.incident_confidence_format, confPct));
                binding.tvRcaConfidence.setVisibility(View.VISIBLE);
                binding.tvRcaHypothesis.setText("Hypothesis: " + (inv.rca.rootCauseHypothesis != null ? inv.rca.rootCauseHypothesis : "N/A"));
                binding.tvRcaHypothesis.setVisibility(View.VISIBLE);
                binding.tvRcaLocation.setText("Location: " + (inv.rca.failureLocation != null ? inv.rca.failureLocation : "N/A"));
                binding.tvRcaLocation.setVisibility(View.VISIBLE);
                binding.tvRcaCondition.setText("Trigger: " + (inv.rca.triggeringCondition != null ? inv.rca.triggeringCondition : "N/A"));
                binding.tvRcaCondition.setVisibility(View.VISIBLE);
            } else {
                binding.tvNoInvestigation.setVisibility(View.VISIBLE);
                binding.tvRcaConfidence.setVisibility(View.GONE);
                binding.tvRcaHypothesis.setVisibility(View.GONE);
                binding.tvRcaLocation.setVisibility(View.GONE);
                binding.tvRcaCondition.setVisibility(View.GONE);
            }
        });

        incidentViewModel.getRemediation().observe(getViewLifecycleOwner(), rem -> {
            if (binding == null) return;
            if (rem != null) {
                binding.tvNoRemediation.setVisibility(View.GONE);
                binding.tvRemediationSummary.setText("Summary: " + (rem.summary != null ? rem.summary : ""));
                binding.tvRemediationSummary.setVisibility(View.VISIBLE);
                binding.tvRemediationRationale.setText("Rationale: " + (rem.rationale != null ? rem.rationale : ""));
                binding.tvRemediationRationale.setVisibility(View.VISIBLE);
                proposedChangeAdapter.setItems(rem.proposedChanges);
                binding.recyclerProposedChanges.setVisibility(View.VISIBLE);
            } else {
                binding.tvNoRemediation.setVisibility(View.VISIBLE);
                binding.tvRemediationSummary.setVisibility(View.GONE);
                binding.tvRemediationRationale.setVisibility(View.GONE);
                binding.recyclerProposedChanges.setVisibility(View.GONE);
            }
        });
    }

    private void bindIncident(IncidentDTO incident) {
        if (binding == null || incident == null) return;

        binding.tvDetailTitle.setText(incident.title != null ? incident.title : "Untitled Incident");
        String serviceText = (incident.service != null ? incident.service : "") +
            " (" + (incident.environment != null ? incident.environment : "") + ") | Project: " +
            (incident.projectId != null ? incident.projectId : "default");
        binding.tvDetailService.setText(serviceText);
        binding.tvDetailSummary.setText(incident.summary != null ? incident.summary : "");
        binding.tvDetailTimestamp.setText(DateFormatHelper.formatIsoUtc(incident.createdAt));

        StatusBadgeHelper.applySeverityChip(binding.chipDetailSeverity, incident.severity);
        StatusBadgeHelper.applyIncidentStatusChip(binding.chipDetailStatus, incident.status);

        updateLifecycleActionButtonsVisibility(incident.status);
        updateButtonEnabledState();
    }

    private void updateLifecycleActionButtonsVisibility(String status) {
        if (binding == null) return;
        String st = (status != null) ? status.toLowerCase().trim() : "open";

        switch (st) {
            case "open":
                binding.btnActionInvestigate.setVisibility(View.VISIBLE);
                binding.btnActionResolve.setVisibility(View.VISIBLE);
                binding.btnActionClose.setVisibility(View.GONE);
                break;
            case "investigating":
                binding.btnActionInvestigate.setVisibility(View.GONE);
                binding.btnActionResolve.setVisibility(View.VISIBLE);
                binding.btnActionClose.setVisibility(View.GONE);
                break;
            case "resolved":
                binding.btnActionInvestigate.setVisibility(View.GONE);
                binding.btnActionResolve.setVisibility(View.GONE);
                binding.btnActionClose.setVisibility(View.VISIBLE);
                break;
            case "closed":
            default:
                binding.btnActionInvestigate.setVisibility(View.GONE);
                binding.btnActionResolve.setVisibility(View.GONE);
                binding.btnActionClose.setVisibility(View.GONE);
                break;
        }
    }

    private void updateButtonEnabledState() {
        if (binding == null) return;
        boolean canMutate = isBackendOnline && !Boolean.TRUE.equals(incidentViewModel.getIsTransitioning().getValue());
        binding.btnActionInvestigate.setEnabled(canMutate);
        binding.btnActionResolve.setEnabled(canMutate);
        binding.btnActionClose.setEnabled(canMutate);
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null; // Enforce zero widget leaks
    }
}
