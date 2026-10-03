package com.sentinelops.mobile.ui.incidents.adapter;

import android.view.LayoutInflater;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;
import com.sentinelops.mobile.data.remote.model.ProposedChangeDTO;
import com.sentinelops.mobile.databinding.ItemProposedChangeBinding;
import java.util.ArrayList;
import java.util.List;

public class ProposedChangeAdapter extends RecyclerView.Adapter<ProposedChangeAdapter.ChangeViewHolder> {

    private final List<ProposedChangeDTO> items = new ArrayList<>();

    public void setItems(List<ProposedChangeDTO> newItems) {
        items.clear();
        if (newItems != null) {
            items.addAll(newItems);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public ChangeViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemProposedChangeBinding binding = ItemProposedChangeBinding.inflate(
            LayoutInflater.from(parent.getContext()), parent, false
        );
        return new ChangeViewHolder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull ChangeViewHolder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static class ChangeViewHolder extends RecyclerView.ViewHolder {
        private final ItemProposedChangeBinding binding;

        ChangeViewHolder(ItemProposedChangeBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(ProposedChangeDTO item) {
            binding.tvChangeType.setText(item.changeType != null ? item.changeType.toUpperCase() : "MODIFY");
            binding.tvChangeFile.setText(item.filePath != null ? item.filePath : "");
            binding.tvChangeDescription.setText(item.description != null ? item.description : "");
            binding.tvChangeReason.setText(item.reason != null ? "Reason: " + item.reason : "");
        }
    }
}
