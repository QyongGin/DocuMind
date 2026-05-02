package com.documind.documind.global.infra.fastapi;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class FastApiClientTest {

    private HttpServer server;
    private FastApiClient fastApiClient;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.start();

        String baseUrl = "http://localhost:" + server.getAddress().getPort();
        fastApiClient = new FastApiClient(WebClient.builder()
                .baseUrl(baseUrl)
                .build(), Duration.ofSeconds(3));
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    @Test
    void uploadDocumentSendsMultipartRequest() throws IOException {
        AtomicReference<String> contentType = new AtomicReference<>();
        AtomicReference<String> requestBody = new AtomicReference<>();

        server.createContext("/documents", exchange -> {
            contentType.set(exchange.getRequestHeaders().getFirst(HttpHeaders.CONTENT_TYPE));
            requestBody.set(readBody(exchange));
            sendJson(exchange, "{\"status\":\"success\",\"filename\":\"sample.pdf\",\"chunks\":3}");
        });

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "sample.pdf",
                MediaType.APPLICATION_PDF_VALUE,
                "pdf-content".getBytes(StandardCharsets.UTF_8)
        );

        FastApiUploadResponse response = fastApiClient.uploadDocument(file, 7L);

        assertEquals(3, response.getChunks());
        assertTrue(contentType.get().startsWith(MediaType.MULTIPART_FORM_DATA_VALUE));
        assertTrue(requestBody.get().contains("name=\"document_id\""));
        assertTrue(requestBody.get().contains("7"));
        assertTrue(requestBody.get().contains("filename=\"sample.pdf\""));
    }

    @Test
    void querySendsJsonRequest() {
        AtomicReference<String> contentType = new AtomicReference<>();
        AtomicReference<String> requestBody = new AtomicReference<>();

        server.createContext("/query", exchange -> {
            contentType.set(exchange.getRequestHeaders().getFirst(HttpHeaders.CONTENT_TYPE));
            requestBody.set(readBody(exchange));
            sendJson(exchange, "{\"answer\":\"답변\",\"sources\":[{\"document_id\":7,\"source\":\"sample.pdf\"}]}");
        });

        FastApiQueryResponse response = fastApiClient.query("질문", 5);

        assertEquals("답변", response.getAnswer());
        assertEquals(1, response.getSources().size());
        assertTrue(contentType.get().startsWith(MediaType.APPLICATION_JSON_VALUE));
        assertTrue(requestBody.get().contains("\"question\":\"질문\""));
        assertTrue(requestBody.get().contains("\"top_k\":5"));
    }

    @Test
    void streamQueryReadsSseDataEvents() {
        AtomicReference<String> contentType = new AtomicReference<>();
        AtomicReference<String> requestBody = new AtomicReference<>();

        server.createContext("/query/stream", exchange -> {
            contentType.set(exchange.getRequestHeaders().getFirst(HttpHeaders.CONTENT_TYPE));
            requestBody.set(readBody(exchange));
            byte[] response = """
                    data: {"token":"안녕"}

                    data: {"done":true,"sources":[]}

                    """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set(HttpHeaders.CONTENT_TYPE, MediaType.TEXT_EVENT_STREAM_VALUE);
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });

        List<String> events = fastApiClient.streamQuery("질문", 5)
                .collectList()
                .block(Duration.ofSeconds(3));

        assertEquals(List.of("{\"token\":\"안녕\"}", "{\"done\":true,\"sources\":[]}"), events);
        assertTrue(contentType.get().startsWith(MediaType.APPLICATION_JSON_VALUE));
        assertTrue(requestBody.get().contains("\"question\":\"질문\""));
        assertTrue(requestBody.get().contains("\"top_k\":5"));
    }

    private String readBody(HttpExchange exchange) throws IOException {
        return new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    }

    private void sendJson(HttpExchange exchange, String body) throws IOException {
        byte[] response = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE);
        exchange.sendResponseHeaders(200, response.length);
        exchange.getResponseBody().write(response);
        exchange.close();
    }
}
