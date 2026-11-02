-- #213 처리 기록(ADR-0052): 답 하나를 만든 프롬프트, 단계별 걸린 초, 근거 후보별 검색 점수, 모델 설정.
-- 대화 기록과 따로 두고 보관 기간(chat.trace.retention, 기본 30일)이 지나면 행을 지운다.
CREATE TABLE IF NOT EXISTS chat_message_traces (
  message_id BIGINT NOT NULL,
  trace JSON NOT NULL,
  created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (message_id),
  KEY idx_chat_message_traces_created_at (created_at),
  CONSTRAINT fk_chat_message_traces_message_id FOREIGN KEY (message_id) REFERENCES chat_messages (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
