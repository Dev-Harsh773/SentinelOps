package com.sentinelops.mobile.workers;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.Build;
import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.data.local.AppPreferences;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import android.app.PendingIntent;
import android.content.Intent;
import com.sentinelops.mobile.data.remote.model.IncidentDTO;
import com.sentinelops.mobile.ui.main.MainActivity;
import java.util.List;
import java.util.concurrent.TimeUnit;
import retrofit2.Response;

public class IncidentPollingWorker extends Worker {

    public static final String CHANNEL_ID = "incident_alerts";
    public static final String CHANNEL_NAME = "Incident Alerts";
    public static final String UNIQUE_WORK_NAME = "SentinelOpsIncidentPollingWorker";

    public static final String EXTRA_INCIDENT_ID = "incident_id";
    public static final String EXTRA_PROJECT_ID = "project_id";

    public IncidentPollingWorker(@NonNull Context context, @NonNull WorkerParameters workerParams) {
        super(context, workerParams);
    }

    public static void schedule(@NonNull Context context) {
        PeriodicWorkRequest workRequest = new PeriodicWorkRequest.Builder(
            IncidentPollingWorker.class,
            15, TimeUnit.MINUTES
        ).setConstraints(
            new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
        ).build();

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            UNIQUE_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            workRequest
        );
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        AppPreferences prefs = new AppPreferences(context);
        String activeProjectId = prefs.getActiveProjectId();
        String backendUrl = prefs.getBackendUrl();

        if (activeProjectId == null || activeProjectId.trim().isEmpty()) {
            return Result.success();
        }

        try {
            ApiClientFactory clientFactory = new ApiClientFactory(backendUrl);
            Response<List<IncidentDTO>> response = clientFactory.getApi().listIncidents().execute();
            if (!response.isSuccessful() || response.body() == null) {
                return Result.retry();
            }

            List<IncidentDTO> incidents = response.body();
            evaluateAndNotify(context, prefs, activeProjectId, incidents);
            return Result.success();
        } catch (Exception e) {
            return Result.retry();
        }
    }

    public static int evaluateAndNotify(Context context, AppPreferences prefs, String activeProjectId, List<IncidentDTO> incidents) {
        if (incidents == null || activeProjectId == null) return 0;

        int notifiedCount = 0;
        for (IncidentDTO incident : incidents) {
            if (incident == null || incident.id == null) continue;

            // 1. Must belong to active project
            if (!activeProjectId.equals(incident.projectId)) {
                continue;
            }

            // 2. Status must be actionable: open or investigating
            String status = incident.status != null ? incident.status.toLowerCase().trim() : "";
            if (!("open".equals(status) || "investigating".equals(status))) {
                continue;
            }

            // 3. Severity must be alerting: high or critical
            String severity = incident.severity != null ? incident.severity.toLowerCase().trim() : "";
            if (!("high".equals(severity) || "critical".equals(severity))) {
                continue;
            }

            // 4. Must not have already alerted
            if (prefs.isIncidentAlerted(incident.id)) {
                continue;
            }

            // Dispatch OS notification if context is provided
            if (context != null) {
                dispatchNotification(context, incident);
            }

            // Record as alerted in bounded set
            prefs.addAlertedIncidentId(incident.id);
            notifiedCount++;
        }
        return notifiedCount;
    }

    public static Intent createNotificationIntent(Context context, IncidentDTO incident) {
        Intent intent = new Intent(context, MainActivity.class);
        intent.putExtra(EXTRA_INCIDENT_ID, incident.id);
        intent.putExtra(EXTRA_PROJECT_ID, incident.projectId);
        intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return intent;
    }

    public static NotificationCompat.Builder buildNotification(Context context, IncidentDTO incident) {
        String title = "🚨 " + (incident.severity != null ? incident.severity.toUpperCase() : "HIGH") + " Incident: " + (incident.title != null ? incident.title : "New Incident");
        String text = incident.summary != null && !incident.summary.isEmpty() ? incident.summary : "Incident detected requiring operational review.";

        Intent intent = createNotificationIntent(context, incident);

        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        int requestCode = incident.id != null ? incident.id.hashCode() : 0;
        PendingIntent pendingIntent = PendingIntent.getActivity(context, requestCode, intent, flags);

        return new NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_sentinel_logo)
            .setContentTitle(title)
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true);
    }

    private static void dispatchNotification(Context context, IncidentDTO incident) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_HIGH
            );
            channel.setDescription("Alerts for newly detected incidents");
            manager.createNotificationChannel(channel);
        }

        NotificationCompat.Builder builder = buildNotification(context, incident);
        int notifId = incident.id != null ? incident.id.hashCode() : 1;
        manager.notify(notifId, builder.build());
    }
}
