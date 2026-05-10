package com.documind.documind.global.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * 문서 색인 백그라운드 처리를 위한 비동기 실행기를 설정한다.
 */
// @Configuration: 문서 처리 전용 Executor Bean을 애플리케이션 컨텍스트에 등록한다.
@Configuration
// @EnableAsync: @Async 메서드가 별도 스레드에서 실행되도록 활성화한다.
@EnableAsync
public class DocumentProcessingAsyncConfig {

    /**
     * 문서 업로드 후 FastAPI 색인 처리를 담당하는 Executor이다.
     *
     * @param corePoolSize 기본 스레드 수
     * @param maxPoolSize  최대 스레드 수
     * @param queueCapacity 대기열 크기
     * @return 문서 처리 전용 Executor
     */
    @Bean(name = "documentProcessingExecutor")
    public Executor documentProcessingExecutor(
            @Value("${document.processing.core-pool-size:1}") int corePoolSize,
            @Value("${document.processing.max-pool-size:1}") int maxPoolSize,
            @Value("${document.processing.queue-capacity:20}") int queueCapacity
    ) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(corePoolSize);
        executor.setMaxPoolSize(maxPoolSize);
        executor.setQueueCapacity(queueCapacity);
        executor.setThreadNamePrefix("document-processing-");
        executor.initialize();
        return executor;
    }
}
