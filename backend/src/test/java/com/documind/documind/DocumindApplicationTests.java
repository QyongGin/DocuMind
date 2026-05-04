package com.documind.documind;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

// @SpringBootTest: 스프링 애플리케이션 컨텍스트가 정상 기동되는지 검증
// @ActiveProfiles: 테스트 전용 application-test.yaml 설정을 로드한다.
@SpringBootTest
@ActiveProfiles("test")
class DocumindApplicationTests {

	@Test
	void contextLoads() {
	}

}
