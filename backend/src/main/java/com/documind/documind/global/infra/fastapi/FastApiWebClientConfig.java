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

    public static final Duration RESPONSE_TIMEOUT = Duration.ofSeconds(180);

    // @Bean: FastAPI 전용 WebClient를 스프링 빈으로 등록
    @Bean
    public WebClient fastApiWebClient(@Value("${fastapi.url}") String baseUrl) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 5_000)
                // 임베딩 모델 로드 + ChromaDB 검색 + EXAONE 첫 토큰 생성 시간을 고려해 180초로 설정
                .responseTimeout(RESPONSE_TIMEOUT);

        return WebClient.builder()
                .baseUrl(baseUrl)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}
