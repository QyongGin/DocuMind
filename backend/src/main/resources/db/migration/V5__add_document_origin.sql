-- #205 참고한 문서(ADR-0050·0051): 문서가 게시된 곳(사이트·게시판·제목)과 첨부의 게시글. 모두 선택이다
ALTER TABLE documents
  ADD COLUMN origin_site VARCHAR(50) DEFAULT NULL,
  ADD COLUMN origin_site_name VARCHAR(100) DEFAULT NULL,
  ADD COLUMN origin_board VARCHAR(100) DEFAULT NULL,
  ADD COLUMN origin_title VARCHAR(500) DEFAULT NULL,
  ADD COLUMN origin_parent_title VARCHAR(500) DEFAULT NULL,
  ADD COLUMN origin_parent_url VARCHAR(1000) DEFAULT NULL;
