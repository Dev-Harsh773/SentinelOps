package com.sentinelops.mobile.ui.settings;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.databinding.FragmentSettingsBinding;

public class SettingsFragment extends Fragment {

    private FragmentSettingsBinding binding;
    private SettingsViewModel viewModel;

    @Nullable
    @Override
    public View onCreateView(
        @NonNull LayoutInflater inflater,
        @Nullable ViewGroup container,
        @Nullable Bundle savedInstanceState
    ) {
        binding = FragmentSettingsBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        viewModel = new ViewModelProvider(this).get(SettingsViewModel.class);

        binding.btnTestConnection.setOnClickListener(v -> {
            String url = binding.etBackendUrl.getText() != null ?
                binding.etBackendUrl.getText().toString().trim() : "";
            if (!url.isEmpty()) {
                viewModel.testConnection(url);
            }
        });

        binding.rgPollingInterval.setOnCheckedChangeListener((group, checkedId) -> {
            if (checkedId == R.id.rb_polling_30s) {
                viewModel.setPollingInterval(30);
            } else if (checkedId == R.id.rb_polling_60s) {
                viewModel.setPollingInterval(60);
            } else if (checkedId == R.id.rb_polling_manual) {
                viewModel.setPollingInterval(0);
            }
        });

        observeState();
    }

    private void observeState() {
        viewModel.getBackendUrl().observe(getViewLifecycleOwner(), url -> {
            if (binding == null) return;
            if (url != null && !url.equals(binding.etBackendUrl.getText().toString())) {
                binding.etBackendUrl.setText(url);
            }
        });

        viewModel.getPollingInterval().observe(getViewLifecycleOwner(), interval -> {
            if (binding == null) return;
            int sec = (interval != null) ? interval : 30;
            if (sec == 60) {
                binding.rbPolling60s.setChecked(true);
            } else if (sec == 0) {
                binding.rbPollingManual.setChecked(true);
            } else {
                binding.rbPolling30s.setChecked(true);
            }
        });

        viewModel.getIsTesting().observe(getViewLifecycleOwner(), testing -> {
            if (binding == null) return;
            boolean inProgress = Boolean.TRUE.equals(testing);
            binding.progressConnectionTest.setVisibility(inProgress ? View.VISIBLE : View.GONE);
            binding.btnTestConnection.setEnabled(!inProgress);
        });

        viewModel.getTestResult().observe(getViewLifecycleOwner(), result -> {
            if (binding == null) return;
            if (result != null) {
                binding.tvConnectionTestResult.setVisibility(View.VISIBLE);
                binding.tvConnectionTestResult.setText(result);
            } else {
                binding.tvConnectionTestResult.setVisibility(View.GONE);
            }
        });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null; // Enforce zero widget leaks
    }
}
