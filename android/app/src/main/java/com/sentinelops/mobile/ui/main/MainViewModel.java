package com.sentinelops.mobile.ui.main;

import android.app.Application;
import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.local.AppPreferences;
import com.sentinelops.mobile.data.remote.model.ProjectDTO;
import com.sentinelops.mobile.data.repository.BackendHealthRepository;
import com.sentinelops.mobile.data.repository.ProjectRepository;
import com.sentinelops.mobile.di.ServiceLocator;
import com.sentinelops.mobile.ui.common.Resource;
import java.util.List;

public class MainViewModel extends AndroidViewModel {

    private final BackendHealthRepository healthRepository;
    private final ProjectRepository projectRepository;
    private final AppPreferences appPreferences;

    private final MutableLiveData<Resource<List<ProjectDTO>>> projectsResource = new MutableLiveData<>();
    private final MutableLiveData<ProjectDTO> selectedProject = new MutableLiveData<>(null);
    private final MutableLiveData<String> activeProjectId = new MutableLiveData<>(null);

    public MainViewModel(@NonNull Application application) {
        super(application);
        ServiceLocator locator = ServiceLocator.getInstance(application);
        this.healthRepository = locator.getBackendHealthRepository();
        this.projectRepository = locator.getProjectRepository();
        this.appPreferences = locator.getAppPreferences();

        loadProjects();
    }

    // Visible for testing
    public MainViewModel(@NonNull Application application,
                         BackendHealthRepository healthRepository,
                         ProjectRepository projectRepository,
                         AppPreferences appPreferences) {
        super(application);
        this.healthRepository = healthRepository;
        this.projectRepository = projectRepository;
        this.appPreferences = appPreferences;
    }

    public LiveData<Boolean> getIsOnline() {
        return healthRepository.getIsOnline();
    }

    public LiveData<Resource<List<ProjectDTO>>> getProjectsResource() {
        return projectsResource;
    }

    public LiveData<ProjectDTO> getSelectedProject() {
        return selectedProject;
    }

    public LiveData<String> getActiveProjectId() {
        return activeProjectId;
    }

    public void loadProjects() {
        projectsResource.setValue(Resource.loading(null));
        projectRepository.listProjects().observeForever(resource -> {
            if (resource == null) return;
            projectsResource.postValue(resource);

            if (resource.isSuccess() && resource.data != null) {
                resolveActiveProject(resource.data);
            }
        });
    }

    public void resolveActiveProject(List<ProjectDTO> list) {
        if (list == null || list.isEmpty()) {
            selectedProject.postValue(null);
            activeProjectId.postValue(null);
            return;
        }

        String savedId = appPreferences.getSavedProjectId();
        ProjectDTO matched = null;

        if (savedId != null && !savedId.trim().isEmpty()) {
            for (ProjectDTO p : list) {
                if (savedId.equals(p.projectId)) {
                    matched = p;
                    break;
                }
            }
        }

        // Fallback: If no saved project exists or saved project is no longer registered,
        // automatically select the first available project.
        if (matched == null) {
            matched = list.get(0);
        }

        selectProject(matched);
    }

    public void selectProject(ProjectDTO project) {
        if (project == null) {
            selectedProject.postValue(null);
            activeProjectId.postValue(null);
            appPreferences.setActiveProjectId(null);
            return;
        }

        selectedProject.postValue(project);
        activeProjectId.postValue(project.projectId);
        appPreferences.setActiveProjectId(project.projectId);
    }
}
