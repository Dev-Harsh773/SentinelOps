package com.sentinelops.mobile.ui.overview;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.navigation.Navigation;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.databinding.FragmentOverviewBinding;
import com.sentinelops.mobile.ui.common.DateFormatHelper;
import com.sentinelops.mobile.ui.main.MainViewModel;

public class OverviewFragment extends Fragment {

    private FragmentOverviewBinding binding;
    private OverviewViewModel overviewViewModel;
    private MainViewModel mainViewModel;

    @Nullable
    @Override
    public View onCreateView(
        @NonNull LayoutInflater inflater,
        @Nullable ViewGroup container,
        @Nullable Bundle savedInstanceState
    ) {
        binding = FragmentOverviewBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        overviewViewModel = new ViewModelProvider(this).get(OverviewViewModel.class);
        mainViewModel = new ViewModelProvider(requireActivity()).get(MainViewModel.class);

        binding.swipeRefresh.setOnRefreshListener(this::triggerRefresh);

        // Clickable cards navigate to corresponding tabs as top-level destinations
        androidx.navigation.NavOptions cardNavOptions = new androidx.navigation.NavOptions.Builder()
            .setLaunchSingleTop(true)
            .setRestoreState(true)
            .setPopUpTo(R.id.nav_overview, false, true)
            .build();

        binding.cardIncidents.setOnClickListener(v ->
            Navigation.findNavController(v).navigate(R.id.nav_incidents, null, cardNavOptions)
        );
        binding.cardConnectors.setOnClickListener(v ->
            Navigation.findNavController(v).navigate(R.id.nav_connectors, null, cardNavOptions)
        );
        binding.cardNotifications.setOnClickListener(v ->
            Navigation.findNavController(v).navigate(R.id.nav_notifications, null, cardNavOptions)
        );

        observeState();
    }

    private void triggerRefresh() {
        String activeId = mainViewModel.getActiveProjectId().getValue();
        if (activeId != null) {
            overviewViewModel.refresh(activeId);
        } else {
            binding.swipeRefresh.setRefreshing(false);
        }
    }

    private void observeState() {
        mainViewModel.getActiveProjectId().observe(getViewLifecycleOwner(), projectId -> {
            if (binding == null) return;
            if (projectId != null) {
                overviewViewModel.refresh(projectId);
            }
        });

        overviewViewModel.getIsLoading().observe(getViewLifecycleOwner(), loading -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(Boolean.TRUE.equals(loading));
        });

        overviewViewModel.getOverviewData().observe(getViewLifecycleOwner(), data -> {
            if (binding == null || data == null) return;

            if (data.errorMessage != null) {
                binding.tvErrorMessage.setVisibility(View.VISIBLE);
                binding.tvErrorMessage.setText(data.errorMessage);
            } else {
                binding.tvErrorMessage.setVisibility(View.GONE);
            }

            if (data.project != null) {
                binding.tvProjectName.setText(data.project.name != null ? data.project.name : data.project.projectId);
                binding.tvProjectWorkspace.setText(data.project.workspacePath != null ? data.project.workspacePath : "");
                if (data.project.lastIndexedAt != null) {
                    binding.tvLastIndexed.setText(getString(R.string.overview_last_indexed,
                        DateFormatHelper.formatIsoUtc(data.project.lastIndexedAt)));
                } else {
                    binding.tvLastIndexed.setText(R.string.overview_not_indexed);
                }
            }

            binding.tvActiveIncidentsCount.setText(String.valueOf(data.activeIncidentsCount));
            binding.tvConnectorsSummary.setText(getString(R.string.connector_operational,
                data.healthyConnectorsCount + " Healthy / " + data.degradedConnectorsCount + " Degraded"));
            binding.tvUnreadNotificationsCount.setText(String.valueOf(data.unreadNotificationsCount));
        });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null; // Enforces zero view capture leaks
    }
}
