# 수동 DB 스키마 적용 Runbook

`application-prod.yaml`은 `spring.jpa.hibernate.ddl-auto=validate`를 사용한다.
이 설정은 현재 DB 스키마가 JPA 엔티티와 맞는지만 검증하고, 테이블을 생성하거나 수정하지 않는다.

운영 profile을 처음 시작하거나 엔티티 변경을 배포하기 전에는 이 디렉터리의 SQL DDL을 대상 MySQL DB에 먼저 적용한다.

## 최초 배포

1. 대상 DB가 생성되어 있는지 확인한다.
2. `schema.sql`을 대상 DB에 적용한다.
3. `SPRING_PROFILES_ACTIVE=prod`로 backend를 시작한다.
4. Hibernate schema validation 오류 없이 backend가 시작되는지 확인한다.

예시:

```bash
mysql -h <host> -u <user> -p <database> < backend/src/main/resources/db/manual/schema.sql
```

## 스키마 변경

Flyway 또는 Liquibase를 도입하기 전까지는 모든 엔티티/스키마 변경 시 이 SQL 파일을 함께 수정한다.
수정된 SQL은 운영 profile backend를 재시작하기 전에 먼저 DB에 적용한다.

장기적으로는 이 수동 runbook을 `src/main/resources/db/migration/`의 버전 관리 마이그레이션으로 대체한다.
그때도 운영 환경의 `ddl-auto=validate`는 유지하고, 스키마 변경은 Flyway 또는 Liquibase가 담당하도록 한다.
