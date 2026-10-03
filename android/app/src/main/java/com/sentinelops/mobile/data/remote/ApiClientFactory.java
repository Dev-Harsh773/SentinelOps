package com.sentinelops.mobile.data.remote;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.util.concurrent.TimeUnit;
import okhttp3.OkHttpClient;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class ApiClientFactory {

    private final Gson gson;
    private final OkHttpClient okHttpClient;
    private String currentBaseUrl;
    private SentinelOpsApi apiInstance;

    public ApiClientFactory(String initialBaseUrl) {
        this.gson = new GsonBuilder().create();

        HttpLoggingInterceptor loggingInterceptor = new HttpLoggingInterceptor();
        loggingInterceptor.setLevel(HttpLoggingInterceptor.Level.BASIC);

        this.okHttpClient = new OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .addInterceptor(loggingInterceptor)
            .build();

        updateBaseUrl(initialBaseUrl);
    }

    public synchronized void updateBaseUrl(String newBaseUrl) {
        String normalizedUrl = newBaseUrl.trim();
        if (!normalizedUrl.endsWith("/")) {
            normalizedUrl += "/";
        }
        if (!normalizedUrl.equals(currentBaseUrl) || apiInstance == null) {
            this.currentBaseUrl = normalizedUrl;
            Retrofit retrofit = new Retrofit.Builder()
                .baseUrl(this.currentBaseUrl)
                .client(okHttpClient)
                .addConverterFactory(GsonConverterFactory.create(gson))
                .build();
            this.apiInstance = retrofit.create(SentinelOpsApi.class);
        }
    }

    public synchronized SentinelOpsApi getApi() {
        return apiInstance;
    }

    public synchronized String getBaseUrl() {
        return currentBaseUrl;
    }

    public OkHttpClient getOkHttpClient() {
        return okHttpClient;
    }

    public Gson getGson() {
        return gson;
    }
}
