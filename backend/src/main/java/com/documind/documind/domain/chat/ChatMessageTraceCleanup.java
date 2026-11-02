package com.documind.documind.domain.chat;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDateTime;

/**
 * 보관 기간이 지난 처리 기록을 매일 지운다(ADR-0052 결정 3). 모델 원문 답과 검색 후보 목록은 대화 기록에 남는다.
 */
@Slf4j
@Component
public class ChatMessageTraceCleanup {

    private final ChatMessageTraceRepository chatMessageTraceRepository;
    private final Duration retention;

    /**
     * @param chatMessageTraceRepository 처리 기록 저장소
     * @param retention                  보관 기간(chat.trace.retention)
     */
    public ChatMessageTraceCleanup(ChatMessageTraceRepository chatMessageTraceRepository,
                                   @Value("${chat.trace.retention:30d}") Duration retention) {
        this.chatMessageTraceRepository = chatMessageTraceRepository;
        this.retention = retention;
    }

    /**
     * 저장한 지 보관 기간이 지난 처리 기록을 지운다. 실행 시각은 chat.trace.cleanup-cron(기본 매일 04:30)이다.
     */
    @Scheduled(cron = "${chat.trace.cleanup-cron:0 30 4 * * *}")
    public void deleteExpired() {
        int deleted = chatMessageTraceRepository.deleteCreatedBefore(LocalDateTime.now().minus(retention));
        if (deleted > 0) {
            log.info("보관 기간이 지난 처리 기록 {}건을 지웠습니다. 보관 기간={}", deleted, retention);
        }
    }
}
