import os

# LANGFUSE_SECRET_KEY가 설정된 경우에만 Langfuse SDK를 임포트해 트레이싱을 활성화한다.
# 환경변수가 없으면 None을 반환해 파이프라인이 그대로 실행되도록 한다 (트레이싱 선택적 적용).
_LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_SECRET_KEY"))


def get_langfuse_handler(**kwargs):
    """
    LangChain 체인에 주입할 Langfuse CallbackHandler를 반환한다.
    LANGFUSE_SECRET_KEY 미설정 시 None을 반환한다.

    langfuse 4.x에서 CallbackHandler는 langfuse.langchain 모듈에 위치한다.
    SDK는 LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_HOST 환경변수를
    자동으로 읽으므로 별도 인자 없이 호출 가능하다.
    """
    if not _LANGFUSE_ENABLED:
        return None

    from langfuse.langchain import CallbackHandler
    return CallbackHandler(**kwargs)
