package com.sentinelops.mobile.ui.connectors.adapter;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;
import com.sentinelops.mobile.data.remote.model.ConnectorResponseDTO;
import com.sentinelops.mobile.databinding.ItemConnectorBinding;
import com.sentinelops.mobile.ui.common.DateFormatHelper;
import com.sentinelops.mobile.ui.common.StatusBadgeHelper;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class ConnectorAdapter extends RecyclerView.Adapter<ConnectorAdapter.ConnectorViewHolder> {

    public interface OnConnectorTestClickListener {
        void onConnectorTestClick(ConnectorResponseDTO connector);
    }

    private final List<ConnectorResponseDTO> items = new ArrayList<>();
    private final OnConnectorTestClickListener testClickListener;
    private final Set<String> testingConnectors = new HashSet<>();
    private boolean isOnline = true;

    public ConnectorAdapter(OnConnectorTestClickListener testClickListener) {
        this.testClickListener = testClickListener;
    }

    public void setItems(List<ConnectorResponseDTO> newItems) {
        items.clear();
        if (newItems != null) {
            items.addAll(newItems);
        }
        notifyDataSetChanged();
    }

    public void setOnline(boolean online) {
        this.isOnline = online;
        notifyDataSetChanged();
    }

    public void setTesting(String connectorId, boolean testing) {
        if (testing) {
            testingConnectors.add(connectorId);
        } else {
            testingConnectors.remove(connectorId);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public ConnectorViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemConnectorBinding binding = ItemConnectorBinding.inflate(
            LayoutInflater.from(parent.getContext()), parent, false
        );
        return new ConnectorViewHolder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull ConnectorViewHolder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    class ConnectorViewHolder extends RecyclerView.ViewHolder {
        private final ItemConnectorBinding binding;

        ConnectorViewHolder(ItemConnectorBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(ConnectorResponseDTO item) {
            binding.tvConnectorName.setText(item.name != null ? item.name : item.connectorId);
            binding.chipConnectorType.setText(item.connectorType != null ? item.connectorType.toUpperCase() : "POLLER");

            if (item.config != null && item.config.url != null) {
                binding.tvConnectorUrl.setVisibility(View.VISIBLE);
                binding.tvConnectorUrl.setText(item.config.url);
            } else {
                binding.tvConnectorUrl.setVisibility(View.GONE);
            }

            if (item.health != null) {
                StatusBadgeHelper.applyOperationalStatusChip(
                    binding.chipOperationalStatus, item.health.operationalStatus
                );
                String targetStatus = item.health.targetStatus != null ? item.health.targetStatus.toUpperCase() : "UNKNOWN";
                binding.chipTargetStatus.setText("TARGET: " + targetStatus);

                if (item.health.lastPollAt != null) {
                    binding.tvConnectorLastPoll.setText("Last poll: " + DateFormatHelper.formatRelative(item.health.lastPollAt));
                } else {
                    binding.tvConnectorLastPoll.setText("No poll history");
                }
            } else {
                StatusBadgeHelper.applyOperationalStatusChip(binding.chipOperationalStatus, "healthy");
                binding.chipTargetStatus.setText("TARGET: UNKNOWN");
                binding.tvConnectorLastPoll.setText("No diagnostic data");
            }

            boolean isTesting = testingConnectors.contains(item.connectorId);
            binding.progressConnectorTest.setVisibility(isTesting ? View.VISIBLE : View.GONE);
            binding.btnConnectorTest.setEnabled(isOnline && !isTesting);

            binding.btnConnectorTest.setOnClickListener(v -> {
                if (testClickListener != null && isOnline && !isTesting) {
                    testClickListener.onConnectorTestClick(item);
                }
            });
        }
    }
}
