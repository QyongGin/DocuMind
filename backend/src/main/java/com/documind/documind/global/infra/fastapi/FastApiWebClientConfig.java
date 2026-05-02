package com.documind.documind.global.infra.fastapi;

import io.netty.channel.ChannelOption;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;

// FastAPI 연동 전용 WebClient 설정
// @Configuration: FastAPI HTTP 클라이언트 빈 설정을 스프링 컨테이너에 등록
@Configuration
public class FastApiWebClientConfig {

    // @Bean: FastAPI 전용 WebClient를 스프링 빈으로 등록
    @Bean
    public WebClient fastApiBlockingWebClient(
            @Value("${fastapi.url}") String baseUrl,
            @Value("${fastapi.connect-timeout:5s}") Duration connectTimeout,
            @Value("${fastapi.response-timeout:180s}") Duration responseTimeout
    ) {
        HttpClient httpClient = createBaseHttpClient(connectTimeout)
                // 문서 업로드와 일반 질의응답은 응답 완료 시간을 제한해 장애를 빠르게 감지
                .responseTimeout(responseTimeout);

        return createWebClient(baseUrl, httpClient);
    }

    // @Bean: FastAPI SSE 스트리밍 전용 WebClient를 스프링 빈으로 등록
    @Bean
    public WebClient fastApiStreamingWebClient(
            @Value("${fastapi.url}") String baseUrl,
            @Value("${fastapi.connect-timeout:5s}") Duration connectTimeout,
            @Value("${fastapi.stream-timeout:0s}") Duration streamTimeout
    ) {
        HttpClient httpClient = createBaseHttpClient(connectTimeout);
        if (!streamTimeout.isZero() && !streamTimeout.isNegative()) {
            httpClient = httpClient.responseTimeout(streamTimeout);
        }

        return createWebClient(baseUrl, httpClient);
    }

    private HttpClient createBaseHttpClient(Duration connectTimeout) {
        return HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, Math.toIntExact(connectTimeout.toMillis()));
    }

    private WebClient createWebClient(String baseUrl, HttpClient httpClient) {
        return WebClient.builder()
                .baseUrl(baseUrl)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}
