package com.sentinelops.mobile.ui.incidents.adapter;

import android.view.LayoutInflater;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;
import com.sentinelops.mobile.data.remote.model.IncidentDTO;
import com.sentinelops.mobile.databinding.ItemIncidentBinding;
import com.sentinelops.mobile.ui.common.DateFormatHelper;
import com.sentinelops.mobile.ui.common.StatusBadgeHelper;
import java.util.ArrayList;
import java.util.List;

public class IncidentAdapter extends RecyclerView.Adapter<IncidentAdapter.IncidentViewHolder> {

    public interface OnIncidentClickListener {
        void onIncidentClick(IncidentDTO incident);
    }

    private final List<IncidentDTO> items = new ArrayList<>();
    private final OnIncidentClickListener listener;

    public IncidentAdapter(OnIncidentClickListener listener) {
        this.listener = listener;
    }

    public void setItems(List<IncidentDTO> newItems) {
        items.clear();
        if (newItems != null) {
            items.addAll(newItems);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public IncidentViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemIncidentBinding binding = ItemIncidentBinding.inflate(
            LayoutInflater.from(parent.getContext()), parent, false
        );
        return new IncidentViewHolder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull IncidentViewHolder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    class IncidentViewHolder extends RecyclerView.ViewHolder {
        private final ItemIncidentBinding binding;

        IncidentViewHolder(ItemIncidentBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(IncidentDTO item) {
            binding.tvIncidentTitle.setText(item.title != null ? item.title : "Untitled Incident");
            String serviceText = item.service != null ? item.service : "";
            if (item.environment != null && !item.environment.isEmpty()) {
                serviceText += " (" + item.environment + ")";
            }
            binding.tvIncidentService.setText(serviceText);
            binding.tvIncidentTime.setText(DateFormatHelper.formatRelative(item.createdAt));

            StatusBadgeHelper.applySeverityChip(binding.chipSeverity, item.severity);
            StatusBadgeHelper.applyIncidentStatusChip(binding.chipStatus, item.status);

            itemView.setOnClickListener(v -> {
                if (listener != null) {
                    listener.onIncidentClick(item);
                }
            });
        }
    }
}
