package com.sentinelops.mobile.data.remote;

import okhttp3.Request;
import okhttp3.Response;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.Test;
import static org.junit.Assert.*;

public class OperatorAuthenticationTest {
    @Test public void authenticatedRequestUsesCurrentToken() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.start();
            String[] token = {"first-token"};
            ApiClientFactory factory = new ApiClientFactory(server.url("/").toString(), () -> token[0]);
            for (String value : new String[]{"first-token", "rotated-token"}) {
                token[0] = value;
                server.enqueue(new MockResponse().setBody("{}"));
                try (Response response = factory.getOkHttpClient().newCall(
                        new Request.Builder().url(server.url("/projects")).build()).execute()) {
                    assertEquals(200, response.code());
                }
                assertEquals("Bearer " + value, server.takeRequest().getHeader("Authorization"));
            }
        }
    }

    @Test public void hostedHttpsUrlAcceptedAndRedirectsDisabled() {
        ApiClientFactory factory = new ApiClientFactory("https://sentinel.example", () -> "token");
        assertEquals("https://sentinel.example/", factory.getBaseUrl());
        assertFalse(factory.getOkHttpClient().followRedirects());
    }

    @Test public void publicCleartextRejectsTokenBeforeNetwork() throws Exception {
        ApiClientFactory factory = new ApiClientFactory("http://example.com", () -> "private-token");
        try {
            factory.getOkHttpClient().newCall(new Request.Builder().url("http://example.com/projects").build()).execute();
            fail("Expected HTTPS requirement");
        } catch (java.io.IOException error) {
            assertTrue(error.getMessage().contains("HTTPS"));
            assertFalse(error.getMessage().contains("private-token"));
        }
    }
}
