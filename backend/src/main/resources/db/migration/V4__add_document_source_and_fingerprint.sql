-- #126 업로드 보강: 문서 대장 정보(출처), 파일 지문(같은 파일 막기), 처리 실패 이유
ALTER TABLE documents
  ADD COLUMN source_ledger_id VARCHAR(200) DEFAULT NULL,
  ADD COLUMN source_url VARCHAR(1000) DEFAULT NULL,
  ADD COLUMN source_posted_at DATE DEFAULT NULL,
  ADD COLUMN academic_year INT DEFAULT NULL,
  ADD COLUMN content_sha256 VARCHAR(64) DEFAULT NULL,
  ADD COLUMN processing_error VARCHAR(500) DEFAULT NULL;

-- 살아 있고 실패하지 않은 문서끼리만 파일 지문이 겹치지 않게 DB에서도 막는다(관리자 여럿이 동시에 올리는 경우).
-- 지운 문서와 실패한 문서는 값이 NULL이 되어 같은 파일을 다시 올릴 수 있다. MySQL 유일 색인은 NULL을 여러 개 허용한다.
-- 엔티티에는 매핑하지 않는다(Hibernate validate는 엔티티에 없는 열을 검사하지 않는다).
ALTER TABLE documents
  ADD COLUMN active_content_sha256 VARCHAR(64) AS (
    CASE
      WHEN is_active = 1 AND (processing_status IS NULL OR processing_status <> 'FAILED') THEN content_sha256
    END
  ) STORED,
  ADD UNIQUE KEY uk_documents_active_content_sha256 (active_content_sha256),
  ADD KEY idx_documents_content_sha256 (content_sha256);
