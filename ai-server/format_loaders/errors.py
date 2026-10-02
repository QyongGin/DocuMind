"""형식 로더가 사용자에게 알릴 오류."""


class UnsupportedDocumentError(Exception):
    """내용을 읽을 수 없는 문서(암호·배포용 HWP, HWP 3.0, 깨진 파일 등). 메시지는 관리자 화면에 그대로 보여도 되는 문장이다."""
