package com.sentinelops.mobile.ui.notifications;

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
import com.sentinelops.mobile.data.remote.model.NotificationResponseDTO;
import com.sentinelops.mobile.databinding.FragmentNotificationFeedBinding;
import com.sentinelops.mobile.ui.main.MainViewModel;
import com.sentinelops.mobile.ui.notifications.adapter.NotificationAdapter;

public class NotificationFeedFragment extends Fragment {

    private FragmentNotificationFeedBinding binding;
    private NotificationViewModel notificationViewModel;
    private MainViewModel mainViewModel;
    private NotificationAdapter adapter;
    private boolean isOnline = true;

    @Nullable
    @Override
    public View onCreateView(
        @NonNull LayoutInflater inflater,
        @Nullable ViewGroup container,
        @Nullable Bundle savedInstanceState
    ) {
        binding = FragmentNotificationFeedBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        notificationViewModel = new ViewModelProvider(this).get(NotificationViewModel.class);
        mainViewModel = new ViewModelProvider(requireActivity()).get(MainViewModel.class);

        adapter = new NotificationAdapter(new NotificationAdapter.OnNotificationActionListener() {
            @Override
            public void onMarkRead(NotificationResponseDTO item) {
                notificationViewModel.markRead(item.notificationId);
            }

            @Override
            public void onRetry(NotificationResponseDTO item) {
                notificationViewModel.retryNotification(item.notificationId);
            }
        });

        binding.recyclerNotifications.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.recyclerNotifications.setAdapter(adapter);

        binding.swipeRefresh.setOnRefreshListener(this::triggerRefresh);

        binding.btnMarkAllRead.setOnClickListener(v -> {
            if (isOnline) {
                notificationViewModel.markAllRead();
            }
        });

        binding.chipFilterAll.setOnClickListener(v -> notificationViewModel.setUnreadOnlyFilter(false));
        binding.chipFilterUnread.setOnClickListener(v -> notificationViewModel.setUnreadOnlyFilter(true));

        observeState();
    }

    private void triggerRefresh() {
        String activeProjectId = mainViewModel.getActiveProjectId().getValue();
        if (activeProjectId != null) {
            notificationViewModel.loadNotifications(activeProjectId);
        } else {
            binding.swipeRefresh.setRefreshing(false);
        }
    }

    private void observeState() {
        mainViewModel.getActiveProjectId().observe(getViewLifecycleOwner(), projectId -> {
            if (binding == null) return;
            if (projectId != null) {
                notificationViewModel.loadNotifications(projectId);
            }
        });

        mainViewModel.getIsOnline().observe(getViewLifecycleOwner(), online -> {
            if (binding == null) return;
            isOnline = Boolean.TRUE.equals(online);
            adapter.setOnline(isOnline);
            binding.btnMarkAllRead.setEnabled(isOnline);
        });

        notificationViewModel.getIsLoading().observe(getViewLifecycleOwner(), loading -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(Boolean.TRUE.equals(loading));
        });

        notificationViewModel.getBatchUnreadCount().observe(getViewLifecycleOwner(), count -> {
            if (binding == null) return;
            binding.tvBatchUnreadLabel.setText(getString(R.string.notification_batch_unread_label, count != null ? count : 0));
        });

        notificationViewModel.getDisplayedNotifications().observe(getViewLifecycleOwner(), notifications -> {
            if (binding == null) return;
            adapter.setItems(notifications);
            if (notifications == null || notifications.isEmpty()) {
                binding.tvEmpty.setVisibility(View.VISIBLE);
            } else {
                binding.tvEmpty.setVisibility(View.GONE);
            }
        });

        notificationViewModel.getActionInFlightId().observe(getViewLifecycleOwner(), actionId -> {
            if (binding == null) return;
            if (actionId != null) {
                adapter.setActionInFlight(actionId, true);
            } else {
                adapter.setActionInFlight("", false);
            }
        });

        notificationViewModel.getFeedbackMessage().observe(getViewLifecycleOwner(), msg -> {
            if (binding == null) return;
            if (msg != null) {
                Toast.makeText(requireContext(), msg, Toast.LENGTH_SHORT).show();
            }
        });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null; // Enforce zero widget leaks
    }
}
