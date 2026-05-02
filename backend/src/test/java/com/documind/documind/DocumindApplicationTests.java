package com.documind.documind;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

// @SpringBootTest: 스프링 애플리케이션 컨텍스트가 정상 기동되는지 검증
@SpringBootTest(properties = {
		"spring.datasource.url=jdbc:h2:mem:documind;MODE=MySQL;DB_CLOSE_DELAY=-1",
		"spring.datasource.username=sa",
		"spring.datasource.password=",
		"spring.datasource.driver-class-name=org.h2.Driver",
		"spring.jpa.hibernate.ddl-auto=create-drop"
})
class DocumindApplicationTests {

	@Test
	void contextLoads() {
	}

}
