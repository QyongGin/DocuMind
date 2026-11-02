-- #208 화면용 답 변환(ADR-0051 결정 3): answer는 화면용 답, raw_answer는 모델 원문 답(출처 번호 포함)
ALTER TABLE chat_messages
  ADD COLUMN raw_answer TEXT DEFAULT NULL;
