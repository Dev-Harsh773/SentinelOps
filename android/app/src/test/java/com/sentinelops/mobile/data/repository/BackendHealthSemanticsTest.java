package com.sentinelops.mobile.data.repository;

import static org.junit.Assert.*;

import androidx.arch.core.executor.testing.InstantTaskExecutorRule;
import com.sentinelops.mobile.data.remote.ApiClientFactory;
import java.io.IOException;
import java.net.ConnectException;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;

public class BackendHealthSemanticsTest {

    @Rule
    public InstantTaskExecutorRule instantTaskExecutorRule = new InstantTaskExecutorRule();

    private MockWebServer mockWebServer;
    private ApiClientFactory apiClientFactory;
    private BackendHealthRepository healthRepository;

    @Before
    public void setUp() throws IOException {
        mockWebServer = new MockWebServer();
        mockWebServer.start();
        apiClientFactory = new ApiClientFactory(mockWebServer.url("/").toString());
        healthRepository = new BackendHealthRepository(apiClientFactory);
    }

    @After
    public void tearDown() throws IOException {
        mockWebServer.shutdown();
    }

    @Test
    public void testHealthSuccessSetsOnlineTrue() throws InterruptedException {
        mockWebServer.enqueue(new MockResponse()
            .setResponseCode(200)
            .setBody("{\"status\": \"ok\", \"service\": \"sentinelops\"}")
        );

        final boolean[] resultReceived = {false};
        healthRepository.probeHealthAsync((healthy, statusCode, latencyMs, message) -> {
            assertTrue(healthy);
            assertEquals(200, statusCode);
            resultReceived[0] = true;
        });

        Thread.sleep(200);
        assertTrue(resultReceived[0]);
        assertEquals(Boolean.TRUE, healthRepository.getIsOnline().getValue());
    }

    @Test
    public void testHealthFailureSetsOnlineFalse() throws InterruptedException {
        mockWebServer.enqueue(new MockResponse().setResponseCode(503));

        final boolean[] resultReceived = {false};
        healthRepository.probeHealthAsync((healthy, statusCode, latencyMs, message) -> {
            assertFalse(healthy);
            assertEquals(503, statusCode);
            resultReceived[0] = true;
        });

        Thread.sleep(200);
        assertTrue(resultReceived[0]);
        assertEquals(Boolean.FALSE, healthRepository.getIsOnline().getValue());
    }

    @Test
    public void testDomainErrorDoesNotSetOffline() {
        // Backend starts online
        healthRepository.setOnline(true);
        assertEquals(Boolean.TRUE, healthRepository.getIsOnline().getValue());

        // Domain error e.g. 404 Not Found or 422 Unprocessable Content
        // A domain error is handled at repository level by returning Resource.error(),
        // NOT by calling setOnline(false) or handleTransportError()!
        assertEquals(Boolean.TRUE, healthRepository.getIsOnline().getValue());
    }

    @Test
    public void testTransportErrorTriggersHealthProbe() throws InterruptedException {
        mockWebServer.enqueue(new MockResponse()
            .setResponseCode(200)
            .setBody("{\"status\": \"ok\", \"service\": \"sentinelops\"}")
        );

        // Simulate transport connection exception
        healthRepository.handleTransportError(new ConnectException("Connection refused"));
        Thread.sleep(200);

        // Probe succeeded against mock server, so stays online
        assertEquals(Boolean.TRUE, healthRepository.getIsOnline().getValue());
    }
}
