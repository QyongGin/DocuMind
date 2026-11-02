package com.documind.documind.global.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

// @Scheduled 작업(처리 기록 지우기 등)을 켠다
@Configuration
@EnableScheduling
public class SchedulingConfig {
}
