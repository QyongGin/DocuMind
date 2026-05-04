CREATE TABLE IF NOT EXISTS users (
  id BIGINT NOT NULL AUTO_INCREMENT,
  created_at DATETIME(6) NOT NULL,
  is_active BIT(1) NOT NULL,
  last_login_at DATETIME(6) DEFAULT NULL,
  password VARCHAR(255) NOT NULL,
  refresh_token VARCHAR(512) DEFAULT NULL,
  role ENUM('ADMIN','USER') NOT NULL,
  username VARCHAR(50) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS categories (
  id BIGINT NOT NULL AUTO_INCREMENT,
  created_at DATETIME(6) NOT NULL,
  name VARCHAR(100) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_categories_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chat_sessions (
  id BIGINT NOT NULL AUTO_INCREMENT,
  created_at DATETIME(6) NOT NULL,
  session_key VARCHAR(100) DEFAULT NULL,
  title VARCHAR(255) DEFAULT NULL,
  updated_at DATETIME(6) NOT NULL,
  user_id BIGINT DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_chat_sessions_session_key (session_key),
  KEY idx_chat_sessions_user_id (user_id),
  CONSTRAINT fk_chat_sessions_user_id FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS documents (
  id BIGINT NOT NULL AUTO_INCREMENT,
  chunk_count INT NOT NULL,
  created_at DATETIME(6) NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  file_size BIGINT NOT NULL,
  is_active BIT(1) NOT NULL,
  mime_type VARCHAR(100) NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  summary TEXT,
  category_id BIGINT DEFAULT NULL,
  uploaded_by BIGINT NOT NULL,
  PRIMARY KEY (id),
  KEY idx_documents_category_id (category_id),
  KEY idx_documents_uploaded_by (uploaded_by),
  CONSTRAINT fk_documents_category_id FOREIGN KEY (category_id) REFERENCES categories (id),
  CONSTRAINT fk_documents_uploaded_by FOREIGN KEY (uploaded_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGINT NOT NULL AUTO_INCREMENT,
  answer TEXT,
  created_at DATETIME(6) NOT NULL,
  question TEXT NOT NULL,
  source_docs JSON DEFAULT NULL,
  session_id BIGINT NOT NULL,
  PRIMARY KEY (id),
  KEY idx_chat_messages_session_id (session_id),
  CONSTRAINT fk_chat_messages_session_id FOREIGN KEY (session_id) REFERENCES chat_sessions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chat_feedback (
  id BIGINT NOT NULL AUTO_INCREMENT,
  created_at DATETIME(6) NOT NULL,
  score TINYINT NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  message_id BIGINT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_chat_feedback_message_id (message_id),
  CONSTRAINT fk_chat_feedback_message_id FOREIGN KEY (message_id) REFERENCES chat_messages (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS prompt_config (
  id BIGINT NOT NULL AUTO_INCREMENT,
  system_prompt TEXT NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  updated_by BIGINT NOT NULL,
  PRIMARY KEY (id),
  KEY idx_prompt_config_updated_by (updated_by),
  CONSTRAINT fk_prompt_config_updated_by FOREIGN KEY (updated_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
