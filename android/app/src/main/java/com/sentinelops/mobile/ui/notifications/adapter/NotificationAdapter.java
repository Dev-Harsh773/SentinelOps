package com.sentinelops.mobile.ui.notifications.adapter;

import android.content.Context;
import android.content.res.ColorStateList;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.RecyclerView;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.data.remote.model.NotificationResponseDTO;
import com.sentinelops.mobile.databinding.ItemNotificationBinding;
import com.sentinelops.mobile.ui.common.DateFormatHelper;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class NotificationAdapter extends RecyclerView.Adapter<NotificationAdapter.NotificationViewHolder> {

    public interface OnNotificationActionListener {
        void onMarkRead(NotificationResponseDTO item);
        void onRetry(NotificationResponseDTO item);
    }

    private final List<NotificationResponseDTO> items = new ArrayList<>();
    private final OnNotificationActionListener actionListener;
    private final Set<String> inFlightActions = new HashSet<>();
    private boolean isOnline = true;

    public NotificationAdapter(OnNotificationActionListener actionListener) {
        this.actionListener = actionListener;
    }

    public void setItems(List<NotificationResponseDTO> newItems) {
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

    public void setActionInFlight(String notificationId, boolean inFlight) {
        if (inFlight) {
            inFlightActions.add(notificationId);
        } else {
            inFlightActions.remove(notificationId);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public NotificationViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemNotificationBinding binding = ItemNotificationBinding.inflate(
            LayoutInflater.from(parent.getContext()), parent, false
        );
        return new NotificationViewHolder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull NotificationViewHolder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    class NotificationViewHolder extends RecyclerView.ViewHolder {
        private final ItemNotificationBinding binding;

        NotificationViewHolder(ItemNotificationBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(NotificationResponseDTO item) {
            Context context = itemView.getContext();
            binding.tvNotificationTitle.setText(item.title != null ? item.title : "Notification");
            binding.tvNotificationMessage.setText(item.message != null ? item.message : "");
            binding.tvNotificationTime.setText(DateFormatHelper.formatRelative(item.createdAt));

            // Channel
            String channel = item.channel != null ? item.channel.toUpperCase() : "FEED";
            binding.chipChannel.setText(channel.replace("_", " "));

            // Delivery Status
            String deliveryStatus = item.deliveryStatus != null ? item.deliveryStatus.toUpperCase() : "DELIVERED";
            binding.chipDeliveryStatus.setText(deliveryStatus);

            if ("FAILED".equalsIgnoreCase(deliveryStatus)) {
                binding.chipDeliveryStatus.setTextColor(ContextCompat.getColor(context, R.color.status_offline));
                binding.chipDeliveryStatus.setChipBackgroundColor(
                    ColorStateList.valueOf(ContextCompat.getColor(context, R.color.status_offline_bg))
                );
                if (item.failureReason != null && !item.failureReason.isEmpty()) {
                    binding.tvFailureReason.setVisibility(View.VISIBLE);
                    binding.tvFailureReason.setText("Failure reason: " + item.failureReason);
                } else {
                    binding.tvFailureReason.setVisibility(View.GONE);
                }
            } else {
                binding.chipDeliveryStatus.setTextColor(ContextCompat.getColor(context, R.color.status_online));
                binding.chipDeliveryStatus.setChipBackgroundColor(
                    ColorStateList.valueOf(ContextCompat.getColor(context, R.color.status_online_bg))
                );
                binding.tvFailureReason.setVisibility(View.GONE);
            }

            boolean isActionLoading = inFlightActions.contains(item.notificationId);
            binding.progressNotificationAction.setVisibility(isActionLoading ? View.VISIBLE : View.GONE);

            // Mark Read Button
            boolean isUnread = "unread".equalsIgnoreCase(item.readStatus);
            if (isUnread) {
                binding.btnMarkRead.setVisibility(View.VISIBLE);
                binding.btnMarkRead.setEnabled(isOnline && !isActionLoading);
                binding.btnMarkRead.setOnClickListener(v -> {
                    if (actionListener != null && isOnline && !isActionLoading) {
                        actionListener.onMarkRead(item);
                    }
                });
            } else {
                binding.btnMarkRead.setVisibility(View.GONE);
            }

            // Retry Button: shown only if webhook failed
            boolean canRetry = "webhook".equalsIgnoreCase(item.channel) && "failed".equalsIgnoreCase(item.deliveryStatus);
            if (canRetry) {
                binding.btnRetryNotification.setVisibility(View.VISIBLE);
                binding.btnRetryNotification.setEnabled(isOnline && !isActionLoading);
                binding.btnRetryNotification.setOnClickListener(v -> {
                    if (actionListener != null && isOnline && !isActionLoading) {
                        actionListener.onRetry(item);
                    }
                });
            } else {
                binding.btnRetryNotification.setVisibility(View.GONE);
            }
        }
    }
}
