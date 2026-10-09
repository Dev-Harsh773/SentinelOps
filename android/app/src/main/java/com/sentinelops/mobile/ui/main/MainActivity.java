package com.sentinelops.mobile.ui.main;

import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.ViewModelProvider;
import androidx.navigation.NavController;
import androidx.navigation.fragment.NavHostFragment;
import androidx.navigation.ui.NavigationUI;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.data.remote.model.ProjectDTO;
import com.sentinelops.mobile.databinding.ActivityMainBinding;
import com.sentinelops.mobile.ui.common.Resource;
import com.sentinelops.mobile.workers.IncidentPollingWorker;
import java.util.List;

public class MainActivity extends AppCompatActivity {

    private static final int REQUEST_CODE_POST_NOTIFICATIONS = 1001;

    private ActivityMainBinding binding;
    private MainViewModel viewModel;
    private NavController navController;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityMainBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        viewModel = new ViewModelProvider(this).get(MainViewModel.class);

        setupNavigation();
        setupProjectSelector();
        observeState();
        checkNotificationPermissionAndScheduleWorker();
        handleNotificationIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleNotificationIntent(intent);
    }

    private void handleNotificationIntent(Intent intent) {
        if (intent == null || !intent.hasExtra(IncidentPollingWorker.EXTRA_INCIDENT_ID)) {
            return;
        }

        String incidentId = intent.getStringExtra(IncidentPollingWorker.EXTRA_INCIDENT_ID);
        String projectId = intent.getStringExtra(IncidentPollingWorker.EXTRA_PROJECT_ID);

        // Remove extras so subsequent configuration changes or recreations do not re-trigger navigation
        intent.removeExtra(IncidentPollingWorker.EXTRA_INCIDENT_ID);
        intent.removeExtra(IncidentPollingWorker.EXTRA_PROJECT_ID);

        if (incidentId == null || incidentId.trim().isEmpty()) {
            return;
        }

        if (projectId != null && !projectId.trim().isEmpty()) {
            String currentProjectId = viewModel.getActiveProjectId().getValue();
            if (!projectId.equals(currentProjectId)) {
                Resource<List<ProjectDTO>> projectsResource = viewModel.getProjectsResource().getValue();
                if (projectsResource != null && projectsResource.data != null) {
                    for (ProjectDTO p : projectsResource.data) {
                        if (projectId.equals(p.projectId)) {
                            viewModel.selectProject(p);
                            break;
                        }
                    }
                }
            }
        }

        if (navController != null) {
            Bundle args = new Bundle();
            args.putString("incident_id", incidentId);
            navController.navigate(R.id.incident_detail, args);
        }
    }

    private void checkNotificationPermissionAndScheduleWorker() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(
                    this,
                    new String[]{android.Manifest.permission.POST_NOTIFICATIONS},
                    REQUEST_CODE_POST_NOTIFICATIONS
                );
            }
        }
        IncidentPollingWorker.schedule(this);
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Refresh project list on app resume if not already loaded
        Resource<List<ProjectDTO>> current = viewModel.getProjectsResource().getValue();
        if (current == null || current.isError() || (current.isSuccess() && current.data == null)) {
            viewModel.loadProjects();
        }
    }

    private void setupNavigation() {
        NavHostFragment navHostFragment =
            (NavHostFragment) getSupportFragmentManager().findFragmentById(R.id.nav_host_fragment);
        if (navHostFragment == null) return;

        this.navController = navHostFragment.getNavController();

        navController.addOnDestinationChangedListener((controller, destination, arguments) -> {
            int destId = destination.getId();
            if (destId == R.id.incident_detail) {
                destId = R.id.nav_incidents;
            }
            android.view.MenuItem item = binding.bottomNavigation.getMenu().findItem(destId);
            if (item != null && !item.isChecked()) {
                item.setChecked(true);
            }
        });

        binding.bottomNavigation.setOnItemSelectedListener(item -> {
            int targetId = item.getItemId();
            androidx.navigation.NavDestination currentDest = navController.getCurrentDestination();
            if (currentDest != null && currentDest.getId() == targetId) {
                return true;
            }

            if (targetId == R.id.nav_overview) {
                boolean popped = navController.popBackStack(R.id.nav_overview, false);
                if (!popped) {
                    androidx.navigation.NavOptions navOptions = new androidx.navigation.NavOptions.Builder()
                        .setLaunchSingleTop(true)
                        .build();
                    navController.navigate(R.id.nav_overview, null, navOptions);
                }
                return true;
            }

            androidx.navigation.NavOptions navOptions = new androidx.navigation.NavOptions.Builder()
                .setLaunchSingleTop(true)
                .setRestoreState(true)
                .setPopUpTo(R.id.nav_overview, false, true)
                .build();
            try {
                navController.navigate(targetId, null, navOptions);
                return true;
            } catch (Exception e) {
                return false;
            }
        });

        binding.bottomNavigation.setOnItemReselectedListener(item -> {
            // Safely ignore reselection of already active tab
        });
    }

    private void setupProjectSelector() {
        View.OnClickListener clickListener = v -> showProjectSelectionDialog();
        binding.layoutProjectSelector.setOnClickListener(clickListener);
        binding.tvSelectedProjectName.setOnClickListener(clickListener);
        binding.ivProjectDropdown.setOnClickListener(clickListener);
    }

    private void showProjectSelectionDialog() {
        Resource<List<ProjectDTO>> resource = viewModel.getProjectsResource().getValue();

        if (resource == null || resource.isLoading()) {
            Toast.makeText(this, R.string.loading_projects, Toast.LENGTH_SHORT).show();
            viewModel.loadProjects();
            return;
        }

        if (resource.isError()) {
            new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.projects_title)
                .setMessage("Failed to load projects: " + resource.message)
                .setPositiveButton("Retry", (dialog, which) -> viewModel.loadProjects())
                .setNegativeButton("Cancel", null)
                .show();
            return;
        }

        List<ProjectDTO> projects = resource.data;
        if (projects == null || projects.isEmpty()) {
            new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.projects_title)
                .setMessage(R.string.no_projects_registered)
                .setPositiveButton("OK", null)
                .setNeutralButton("Refresh", (dialog, which) -> viewModel.loadProjects())
                .show();
            return;
        }

        String[] displayNames = new String[projects.size()];
        int selectedIndex = -1;
        String currentActiveId = viewModel.getActiveProjectId().getValue();

        for (int i = 0; i < projects.size(); i++) {
            ProjectDTO p = projects.get(i);
            String name = (p.name != null && !p.name.trim().isEmpty()) ? p.name : p.projectId;
            displayNames[i] = name;
            if (p.projectId != null && p.projectId.equals(currentActiveId)) {
                selectedIndex = i;
            }
        }

        new MaterialAlertDialogBuilder(this)
            .setTitle(R.string.projects_title)
            .setSingleChoiceItems(displayNames, selectedIndex, (dialog, which) -> {
                if (which >= 0 && which < projects.size()) {
                    ProjectDTO selected = projects.get(which);
                    viewModel.selectProject(selected);
                }
                dialog.dismiss();
            })
            .setNegativeButton("Cancel", null)
            .show();
    }

    private void observeState() {
        viewModel.getIsOnline().observe(this, isOnline -> {
            boolean online = Boolean.TRUE.equals(isOnline);
            if (online) {
                binding.chipConnectivity.setText(R.string.status_online);
                binding.chipConnectivity.setTextColor(ContextCompat.getColor(this, R.color.status_online));
                binding.chipConnectivity.setChipBackgroundColor(
                    ColorStateList.valueOf(ContextCompat.getColor(this, R.color.status_online_bg))
                );
                binding.tvOfflineBanner.setVisibility(View.GONE);

                // If projects were not loaded while offline, load them now
                Resource<List<ProjectDTO>> currentProjects = viewModel.getProjectsResource().getValue();
                if (currentProjects == null || currentProjects.isError()) {
                    viewModel.loadProjects();
                }
            } else {
                binding.chipConnectivity.setText(R.string.status_offline);
                binding.chipConnectivity.setTextColor(ContextCompat.getColor(this, R.color.status_offline));
                binding.chipConnectivity.setChipBackgroundColor(
                    ColorStateList.valueOf(ContextCompat.getColor(this, R.color.status_offline_bg))
                );
                binding.tvOfflineBanner.setVisibility(View.VISIBLE);
            }
        });

        viewModel.getSelectedProject().observe(this, project -> {
            if (project != null) {
                String displayName = (project.name != null && !project.name.trim().isEmpty())
                    ? project.name : project.projectId;
                binding.tvSelectedProjectName.setText(displayName);
            } else {
                binding.tvSelectedProjectName.setText(R.string.select_project_hint);
            }
        });
    }
}
