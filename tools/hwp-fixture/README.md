# 합성 HWP 시험 파일 만들기

`ai-server/tests/fixtures/table_sample.hwp`를 만드는 개발용 도구다. 파일 내용은 지어낸 것이고 학교 문서가 아니다.
저장소가 공개라 학교 문서를 시험 파일로 넣지 않는다.

AI 서버는 HWP 5.0을 파이썬으로 직접 읽는다(`ai-server/format_loaders/hwp5.py`). 시험 파일은 다른 구현인
자바 [hwplib](https://github.com/neolord0/hwplib)(Apache-2.0)으로 써서, 우리 해석기가 우리 쪽 가정에만 맞춰지지 않게 한다.
hwplib은 이 도구에서만 쓰고 서비스 코드에는 넣지 않는다.

본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.

## 들어 있는 표

| 표 | 확인하는 규칙 |
|---|---|
| 표 1 | 맨 윗줄이 전체 폭 한 칸 → 표 위 제목 글줄, 세로 병합 채움, 짧은 가로 병합 채움 |
| 표 2 | 왼쪽 위 칸이 아래로 2줄 병합 → 머리 두 줄을 한 줄로 합침 |
| 표 3 | 칸 하나뿐인 표 → 글 |
| 표 4 | 칸 안의 표 → 바깥 칸 글로 펼침 |

## 다시 만드는 법 (맥북)

hwplib 1.1.9를 Maven Central에서 받는다. SHA-1은 `a185d5504606bef698f2f5a1b31c9fda28b9496a`이다.

```bash
cd tools/hwp-fixture
curl -fsSLO https://repo1.maven.org/maven2/kr/dogfoot/hwplib/1.1.9/hwplib-1.1.9.jar
shasum -a 1 hwplib-1.1.9.jar
javac -cp hwplib-1.1.9.jar MakeHwpFixture.java
java -cp hwplib-1.1.9.jar:. MakeHwpFixture ../../ai-server/tests/fixtures/table_sample.hwp
rm -f hwplib-1.1.9.jar *.class
```

다시 만든 뒤에는 `ai-server/tests/golden/formats/table_sample_hwp.md`와 변환 결과가 같은지 `pytest tests/test_format_loaders.py`로 확인한다.
