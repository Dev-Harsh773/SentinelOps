package com.sentinelops.mobile.ui.common;

import android.content.Context;
import android.content.res.ColorStateList;
import androidx.core.content.ContextCompat;
import com.google.android.material.chip.Chip;
import com.sentinelops.mobile.R;

public class StatusBadgeHelper {

    public static void applySeverityChip(Chip chip, String severity) {
        if (chip == null) return;
        Context context = chip.getContext();
        String sev = (severity != null) ? severity.toLowerCase().trim() : "medium";
        int textColor;
        int bgColor;

        switch (sev) {
            case "critical":
                textColor = ContextCompat.getColor(context, R.color.severity_critical);
                bgColor = ContextCompat.getColor(context, R.color.severity_critical_bg);
                break;
            case "high":
                textColor = ContextCompat.getColor(context, R.color.severity_high);
                bgColor = ContextCompat.getColor(context, R.color.severity_high_bg);
                break;
            case "low":
                textColor = ContextCompat.getColor(context, R.color.severity_low);
                bgColor = ContextCompat.getColor(context, R.color.severity_low_bg);
                break;
            case "medium":
            default:
                textColor = ContextCompat.getColor(context, R.color.severity_medium);
                bgColor = ContextCompat.getColor(context, R.color.severity_medium_bg);
                break;
        }

        chip.setText(sev.toUpperCase());
        chip.setTextColor(textColor);
        chip.setChipBackgroundColor(ColorStateList.valueOf(bgColor));
    }

    public static void applyIncidentStatusChip(Chip chip, String status) {
        if (chip == null) return;
        Context context = chip.getContext();
        String st = (status != null) ? status.toLowerCase().trim() : "open";
        int textColor;

        switch (st) {
            case "open":
                textColor = ContextCompat.getColor(context, R.color.incident_open);
                break;
            case "investigating":
                textColor = ContextCompat.getColor(context, R.color.incident_investigating);
                break;
            case "resolved":
                textColor = ContextCompat.getColor(context, R.color.incident_resolved);
                break;
            case "closed":
            default:
                textColor = ContextCompat.getColor(context, R.color.incident_closed);
                break;
        }

        chip.setText(st.toUpperCase());
        chip.setTextColor(textColor);
        chip.setChipBackgroundColor(ColorStateList.valueOf(ContextCompat.getColor(context, R.color.surface_variant)));
    }

    public static void applyOperationalStatusChip(Chip chip, String operationalStatus) {
        if (chip == null) return;
        Context context = chip.getContext();
        String st = (operationalStatus != null) ? operationalStatus.toLowerCase().trim() : "healthy";
        int textColor;
        int bgColor;

        switch (st) {
            case "degraded":
                textColor = ContextCompat.getColor(context, R.color.severity_high);
                bgColor = ContextCompat.getColor(context, R.color.severity_high_bg);
                break;
            case "errored":
                textColor = ContextCompat.getColor(context, R.color.status_offline);
                bgColor = ContextCompat.getColor(context, R.color.status_offline_bg);
                break;
            case "healthy":
            default:
                textColor = ContextCompat.getColor(context, R.color.status_online);
                bgColor = ContextCompat.getColor(context, R.color.status_online_bg);
                break;
        }

        chip.setText(st.toUpperCase());
        chip.setTextColor(textColor);
        chip.setChipBackgroundColor(ColorStateList.valueOf(bgColor));
    }
}
