package com.sentinelops.mobile.ui.incidents;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.navigation.Navigation;
import androidx.recyclerview.widget.LinearLayoutManager;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.databinding.FragmentIncidentListBinding;
import com.sentinelops.mobile.ui.incidents.adapter.IncidentAdapter;
import com.sentinelops.mobile.ui.main.MainViewModel;

public class IncidentListFragment extends Fragment {

    private FragmentIncidentListBinding binding;
    private IncidentViewModel incidentViewModel;
    private MainViewModel mainViewModel;
    private IncidentAdapter adapter;

    @Nullable
    @Override
    public View onCreateView(
        @NonNull LayoutInflater inflater,
        @Nullable ViewGroup container,
        @Nullable Bundle savedInstanceState
    ) {
        binding = FragmentIncidentListBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        incidentViewModel = new ViewModelProvider(this).get(IncidentViewModel.class);
        mainViewModel = new ViewModelProvider(requireActivity()).get(MainViewModel.class);

        adapter = new IncidentAdapter(incident -> {
            Bundle bundle = new Bundle();
            bundle.putString("incident_id", incident.id);
            Navigation.findNavController(requireView()).navigate(R.id.action_incidents_to_detail, bundle);
        });

        binding.recyclerIncidents.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.recyclerIncidents.setAdapter(adapter);

        binding.swipeRefresh.setOnRefreshListener(this::triggerRefresh);
        setupFilterChips();
        observeState();
    }

    private void setupFilterChips() {
        binding.chipFilterAll.setOnClickListener(v -> {
            incidentViewModel.setSeverityFilter("All");
            incidentViewModel.setStatusFilter("All");
        });
        binding.chipFilterOpen.setOnClickListener(v -> incidentViewModel.setStatusFilter("Open"));
        binding.chipFilterInvestigating.setOnClickListener(v -> incidentViewModel.setStatusFilter("Investigating"));
        binding.chipFilterResolved.setOnClickListener(v -> incidentViewModel.setStatusFilter("Resolved"));
        binding.chipFilterClosed.setOnClickListener(v -> incidentViewModel.setStatusFilter("Closed"));
        binding.chipFilterCritical.setOnClickListener(v -> incidentViewModel.setSeverityFilter("Critical"));
    }

    private void triggerRefresh() {
        String activeProjectId = mainViewModel.getActiveProjectId().getValue();
        incidentViewModel.loadIncidents(activeProjectId != null ? activeProjectId : "default");
    }

    private void observeState() {
        mainViewModel.getActiveProjectId().observe(getViewLifecycleOwner(), projectId -> {
            if (binding == null) return;
            incidentViewModel.loadIncidents(projectId != null ? projectId : "default");
        });

        incidentViewModel.getIsLoading().observe(getViewLifecycleOwner(), loading -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(Boolean.TRUE.equals(loading));
        });

        incidentViewModel.getFilteredIncidents().observe(getViewLifecycleOwner(), incidents -> {
            if (binding == null) return;
            adapter.setItems(incidents);
            if (incidents == null || incidents.isEmpty()) {
                binding.tvEmpty.setVisibility(View.VISIBLE);
            } else {
                binding.tvEmpty.setVisibility(View.GONE);
            }
        });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null; // Enforce zero widget leaks
    }
}
