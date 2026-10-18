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
        this(initialBaseUrl, () -> "");
    }

    public ApiClientFactory(String initialBaseUrl, java.util.function.Supplier<String> tokenProvider) {
        this.gson = new GsonBuilder().create();

        HttpLoggingInterceptor loggingInterceptor = new HttpLoggingInterceptor();
        loggingInterceptor.setLevel(HttpLoggingInterceptor.Level.NONE);

        this.okHttpClient = new OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .addInterceptor(chain -> {
                okhttp3.Request request = chain.request();
                String token = tokenProvider.get();
                if (token != null && !token.isEmpty()) {
                    String host = request.url().host();
                    if (!request.url().isHttps() && !host.equals("localhost") &&
                        !host.equals("127.0.0.1") && !host.equals("::1") && !host.equals("10.0.2.2")) {
                        throw new java.io.IOException("Operator authentication requires HTTPS outside localhost");
                    }
                    request = request.newBuilder().header("Authorization", "Bearer " + token).build();
                }
                return chain.proceed(request);
            })
            .addInterceptor(loggingInterceptor)
            .build();

        updateBaseUrl(initialBaseUrl);
    }

    public synchronized void updateBaseUrl(String newBaseUrl) {
        String normalizedUrl = newBaseUrl.trim();
        okhttp3.HttpUrl parsed = okhttp3.HttpUrl.parse(normalizedUrl);
        if (parsed == null || !parsed.username().isEmpty() || !parsed.password().isEmpty()) {
            throw new IllegalArgumentException("Use an HTTP(S) backend URL without credentials");
        }
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
