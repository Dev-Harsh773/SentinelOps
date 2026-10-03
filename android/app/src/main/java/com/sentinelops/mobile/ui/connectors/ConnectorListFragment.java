package com.sentinelops.mobile.ui.connectors;

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
import com.sentinelops.mobile.databinding.FragmentConnectorListBinding;
import com.sentinelops.mobile.ui.connectors.adapter.ConnectorAdapter;
import com.sentinelops.mobile.ui.main.MainViewModel;

public class ConnectorListFragment extends Fragment {

    private FragmentConnectorListBinding binding;
    private ConnectorViewModel connectorViewModel;
    private MainViewModel mainViewModel;
    private ConnectorAdapter adapter;

    @Nullable
    @Override
    public View onCreateView(
        @NonNull LayoutInflater inflater,
        @Nullable ViewGroup container,
        @Nullable Bundle savedInstanceState
    ) {
        binding = FragmentConnectorListBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        connectorViewModel = new ViewModelProvider(this).get(ConnectorViewModel.class);
        mainViewModel = new ViewModelProvider(requireActivity()).get(MainViewModel.class);

        adapter = new ConnectorAdapter(connector -> {
            connectorViewModel.testConnector(connector.connectorId);
        });

        binding.recyclerConnectors.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.recyclerConnectors.setAdapter(adapter);

        binding.swipeRefresh.setOnRefreshListener(this::triggerRefresh);
        observeState();
    }

    private void triggerRefresh() {
        String activeProjectId = mainViewModel.getActiveProjectId().getValue();
        if (activeProjectId != null) {
            connectorViewModel.loadConnectors(activeProjectId);
        } else {
            binding.swipeRefresh.setRefreshing(false);
        }
    }

    private void observeState() {
        mainViewModel.getActiveProjectId().observe(getViewLifecycleOwner(), projectId -> {
            if (binding == null) return;
            if (projectId != null) {
                connectorViewModel.loadConnectors(projectId);
            }
        });

        mainViewModel.getIsOnline().observe(getViewLifecycleOwner(), online -> {
            if (binding == null) return;
            adapter.setOnline(Boolean.TRUE.equals(online));
        });

        connectorViewModel.getIsLoading().observe(getViewLifecycleOwner(), loading -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(Boolean.TRUE.equals(loading));
        });

        connectorViewModel.getConnectorsList().observe(getViewLifecycleOwner(), connectors -> {
            if (binding == null) return;
            adapter.setItems(connectors);
            if (connectors == null || connectors.isEmpty()) {
                binding.tvEmpty.setVisibility(View.VISIBLE);
            } else {
                binding.tvEmpty.setVisibility(View.GONE);
            }
        });

        connectorViewModel.getTestingConnectorId().observe(getViewLifecycleOwner(), testingId -> {
            if (binding == null) return;
            if (testingId != null) {
                adapter.setTesting(testingId, true);
            } else {
                adapter.setTesting("", false);
            }
        });

        connectorViewModel.getTestResultMessage().observe(getViewLifecycleOwner(), message -> {
            if (binding == null) return;
            if (message != null) {
                Toast.makeText(requireContext(), message, Toast.LENGTH_LONG).show();
            }
        });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null; // Enforce zero widget leaks
    }
}
