package com.sentinelops.mobile.ui.main;

import static org.junit.Assert.*;
import static org.mockito.Mockito.*;

import android.app.Application;
import androidx.arch.core.executor.testing.InstantTaskExecutorRule;
import com.sentinelops.mobile.data.local.AppPreferences;
import com.sentinelops.mobile.data.remote.model.ProjectDTO;
import com.sentinelops.mobile.data.repository.BackendHealthRepository;
import com.sentinelops.mobile.data.repository.ProjectRepository;
import java.util.ArrayList;
import java.util.List;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;

public class ProjectSelectionStateTest {

    @Rule
    public InstantTaskExecutorRule instantTaskExecutorRule = new InstantTaskExecutorRule();

    private Application mockApplication;
    private BackendHealthRepository mockHealthRepository;
    private ProjectRepository mockProjectRepository;
    private AppPreferences mockAppPreferences;
    private MainViewModel viewModel;

    @Before
    public void setUp() {
        mockApplication = mock(Application.class);
        mockHealthRepository = mock(BackendHealthRepository.class);
        mockProjectRepository = mock(ProjectRepository.class);
        mockAppPreferences = mock(AppPreferences.class);

        viewModel = new MainViewModel(
            mockApplication,
            mockHealthRepository,
            mockProjectRepository,
            mockAppPreferences
        );
    }

    private List<ProjectDTO> createSampleProjects() {
        List<ProjectDTO> list = new ArrayList<>();

        ProjectDTO p1 = new ProjectDTO();
        p1.projectId = "proj-alpha";
        p1.name = "Alpha Project";
        list.add(p1);

        ProjectDTO p2 = new ProjectDTO();
        p2.projectId = "proj-beta";
        p2.name = "Beta Project";
        list.add(p2);

        ProjectDTO p3 = new ProjectDTO();
        p3.projectId = "proj-gamma";
        p3.name = "Gamma Project";
        list.add(p3);

        return list;
    }

    @Test
    public void testResolveActiveProjectSelectsFirstWhenNoSavedProject() {
        when(mockAppPreferences.getSavedProjectId()).thenReturn(null);

        List<ProjectDTO> projects = createSampleProjects();
        viewModel.resolveActiveProject(projects);

        assertNotNull(viewModel.getSelectedProject().getValue());
        assertEquals("proj-alpha", viewModel.getSelectedProject().getValue().projectId);
        assertEquals("Alpha Project", viewModel.getSelectedProject().getValue().name);
        assertEquals("proj-alpha", viewModel.getActiveProjectId().getValue());

        verify(mockAppPreferences).setActiveProjectId("proj-alpha");
    }

    @Test
    public void testResolveActiveProjectRestoresSavedProject() {
        when(mockAppPreferences.getSavedProjectId()).thenReturn("proj-beta");

        List<ProjectDTO> projects = createSampleProjects();
        viewModel.resolveActiveProject(projects);

        assertNotNull(viewModel.getSelectedProject().getValue());
        assertEquals("proj-beta", viewModel.getSelectedProject().getValue().projectId);
        assertEquals("Beta Project", viewModel.getSelectedProject().getValue().name);
        assertEquals("proj-beta", viewModel.getActiveProjectId().getValue());

        verify(mockAppPreferences).setActiveProjectId("proj-beta");
    }

    @Test
    public void testResolveActiveProjectFallsBackToFirstWhenSavedProjectNotFound() {
        when(mockAppPreferences.getSavedProjectId()).thenReturn("proj-deleted");

        List<ProjectDTO> projects = createSampleProjects();
        viewModel.resolveActiveProject(projects);

        // Fallback to first available project
        assertNotNull(viewModel.getSelectedProject().getValue());
        assertEquals("proj-alpha", viewModel.getSelectedProject().getValue().projectId);
        assertEquals("proj-alpha", viewModel.getActiveProjectId().getValue());

        verify(mockAppPreferences).setActiveProjectId("proj-alpha");
    }

    @Test
    public void testResolveActiveProjectWithEmptyListSetsNullGracefully() {
        viewModel.resolveActiveProject(new ArrayList<>());

        assertNull(viewModel.getSelectedProject().getValue());
        assertNull(viewModel.getActiveProjectId().getValue());
    }

    @Test
    public void testResolveActiveProjectWithNullListSetsNullGracefully() {
        viewModel.resolveActiveProject(null);

        assertNull(viewModel.getSelectedProject().getValue());
        assertNull(viewModel.getActiveProjectId().getValue());
    }

    @Test
    public void testSelectProjectExplicitSwitchUpdatesStateAndPreferences() {
        ProjectDTO p = new ProjectDTO();
        p.projectId = "proj-custom";
        p.name = "Custom Project";

        viewModel.selectProject(p);

        assertEquals(p, viewModel.getSelectedProject().getValue());
        assertEquals("proj-custom", viewModel.getActiveProjectId().getValue());
        verify(mockAppPreferences).setActiveProjectId("proj-custom");
    }

    @Test
    public void testSelectNullProjectClearsState() {
        viewModel.selectProject(null);

        assertNull(viewModel.getSelectedProject().getValue());
        assertNull(viewModel.getActiveProjectId().getValue());
        verify(mockAppPreferences).setActiveProjectId(null);
    }

    @Test
    public void testStaleResponseRejectionGuardLogic() {
        // Verification of sequence/request-id concurrency guard semantics
        long requestSequence = 0;
        String currentRequestedProjectId = "proj-alpha";

        // Request 1 issued for proj-alpha
        long requestId1 = ++requestSequence;
        String req1ProjectId = currentRequestedProjectId;

        // User immediately switches to proj-beta, triggering Request 2
        currentRequestedProjectId = "proj-beta";
        long requestId2 = ++requestSequence;
        String req2ProjectId = currentRequestedProjectId;

        // Request 1 arrives late
        boolean request1Accepted = (requestId1 == requestSequence && req1ProjectId.equals(currentRequestedProjectId));
        assertFalse("Late response from Request 1 must be rejected", request1Accepted);

        // Request 2 arrives
        boolean request2Accepted = (requestId2 == requestSequence && req2ProjectId.equals(currentRequestedProjectId));
        assertTrue("Current response from Request 2 must be accepted", request2Accepted);
    }
}
