package com.sentinelops.mobile.data.repository;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import com.sentinelops.mobile.data.remote.model.HealthResponseDTO;
import java.io.IOException;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import retrofit2.Response;

public class BackendHealthRepository {

    private final ApiClientFactory apiClientFactory;
    private final MutableLiveData<Boolean> isOnlineLiveData = new MutableLiveData<>(true);
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    public interface HealthCheckCallback {
        void onResult(boolean healthy, int statusCode, long latencyMs, String message);
    }

    public BackendHealthRepository(ApiClientFactory apiClientFactory) {
        this.apiClientFactory = apiClientFactory;
    }

    public LiveData<Boolean> getIsOnline() {
        return isOnlineLiveData;
    }

    public void setOnline(boolean online) {
        if (isOnlineLiveData.getValue() == null || isOnlineLiveData.getValue() != online) {
            isOnlineLiveData.postValue(online);
        }
    }

    public void handleTransportError(Throwable t) {
        if (t instanceof ConnectException || t instanceof UnknownHostException || t instanceof SocketTimeoutException) {
            probeHealthAsync(null);
        }
    }

    public void probeHealthAsync(HealthCheckCallback callback) {
        executor.execute(() -> {
            long start = System.currentTimeMillis();
            try {
                Response<HealthResponseDTO> response = apiClientFactory.getApi().getHealth().execute();
                long latency = System.currentTimeMillis() - start;
                if (response.isSuccessful() && response.body() != null) {
                    setOnline(true);
                    if (callback != null) {
                        callback.onResult(true, response.code(), latency, "Service: " + response.body().service);
                    }
                } else {
                    setOnline(false);
                    if (callback != null) {
                        callback.onResult(false, response.code(), latency, "HTTP " + response.code() + ": " + response.message());
                    }
                }
            } catch (IOException e) {
                long latency = System.currentTimeMillis() - start;
                setOnline(false);
                if (callback != null) {
                    callback.onResult(false, 0, latency, "Connection failed: " + e.getMessage());
                }
            }
        });
    }
}
