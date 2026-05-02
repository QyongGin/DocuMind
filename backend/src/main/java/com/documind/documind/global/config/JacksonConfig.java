package com.documind.documind.global.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

// Spring Boot의 JacksonAutoConfiguration은 webmvc + webflux 공존 시
// @ConditionalOnSingleCandidate 조건 실패로 ObjectMapper 빈을 등록하지 못하는 경우가 있다.
// 명시적으로 선언해 해당 조건을 우회하고 전역 Jackson 설정을 일원화한다.
// @Configuration: 이 클래스가 스프링 빈 설정 클래스임을 표시
@Configuration
public class JacksonConfig {

    // @Bean: 메서드가 반환하는 객체를 스프링 컨테이너에 빈으로 등록
    @Bean
    public ObjectMapper objectMapper() {
        return new ObjectMapper()
                // LocalDateTime 등 Java 8 날짜 타입 직렬화 지원
                .registerModule(new JavaTimeModule())
                // 날짜를 타임스탬프 숫자 대신 ISO-8601 문자열로 직렬화
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    }
}
