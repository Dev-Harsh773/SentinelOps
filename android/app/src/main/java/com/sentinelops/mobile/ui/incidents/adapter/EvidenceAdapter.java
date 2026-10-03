package com.sentinelops.mobile.ui.incidents.adapter;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.RecyclerView;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.data.remote.model.EvidenceDTO;
import com.sentinelops.mobile.databinding.ItemEvidenceBinding;
import com.sentinelops.mobile.ui.common.DateFormatHelper;
import java.util.ArrayList;
import java.util.List;

public class EvidenceAdapter extends RecyclerView.Adapter<EvidenceAdapter.EvidenceViewHolder> {

    private final List<EvidenceDTO> items = new ArrayList<>();

    public void setItems(List<EvidenceDTO> newItems) {
        items.clear();
        if (newItems != null) {
            items.addAll(newItems);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public EvidenceViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemEvidenceBinding binding = ItemEvidenceBinding.inflate(
            LayoutInflater.from(parent.getContext()), parent, false
        );
        return new EvidenceViewHolder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull EvidenceViewHolder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static class EvidenceViewHolder extends RecyclerView.ViewHolder {
        private final ItemEvidenceBinding binding;

        EvidenceViewHolder(ItemEvidenceBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(EvidenceDTO item) {
            Context context = itemView.getContext();
            String level = item.level != null ? item.level.toUpperCase() : "INFO";
            binding.tvEvidenceLevel.setText(level);

            if ("ERROR".equals(level)) {
                binding.tvEvidenceLevel.setBackgroundColor(ContextCompat.getColor(context, R.color.level_error));
            } else if ("WARNING".equals(level) || "WARN".equals(level)) {
                binding.tvEvidenceLevel.setBackgroundColor(ContextCompat.getColor(context, R.color.level_warn));
            } else {
                binding.tvEvidenceLevel.setBackgroundColor(ContextCompat.getColor(context, R.color.level_info));
            }

            binding.tvEvidenceTime.setText(DateFormatHelper.formatIsoUtc(item.timestamp));
            binding.tvEvidenceService.setText(item.service != null ? item.service : "");
            binding.tvEvidenceMessage.setText(item.message != null ? item.message : "");
        }
    }
}
