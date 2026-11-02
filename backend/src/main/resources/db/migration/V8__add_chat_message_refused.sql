-- #213 못 답한 질문(ADR-0052 결정 5): 거절 문장만 나간 답(정해 둔 안내를 붙인 답)을 표시하고 최근 것부터 찾는다.
-- 이 칸이 생기기 전 답은 FALSE로 둔다(거절 문장은 백엔드 설정값이라 마이그레이션에서 알아볼 수 없다).
ALTER TABLE chat_messages
  ADD COLUMN refused BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX idx_chat_messages_refused_created_at ON chat_messages (refused, created_at);
