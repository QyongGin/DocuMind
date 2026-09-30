"""pytest 공통 설정.

R0 측정 안전망은 ai-server 모듈을 직접 import 해서 검증한다. 이 conftest는
두 가지를 책임진다.

1. 어떤 cwd 에서 ``pytest`` 를 실행하든 ``from main import ...`` 가 되도록
   ai-server 디렉터리를 ``sys.path`` 앞에 끼운다.
2. ``main`` 은 import 시점에 ChromaDB PersistentClient 를 만들고 cwd 에
   ``./chroma_db`` 를 생성하는 부작용이 있다. 테스트가 실제 색인을 더럽히지
   않도록, import 동안에는 임시 디렉터리로 cwd 를 옮기고 ``CHROMA_HOST`` 를
   제거해 PersistentClient(오프라인) 경로를 강제한다.

원본 스크립트/모듈 로직은 일절 바꾸지 않는다. 안전망만 덧붙인다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

AI_SERVER_DIR = Path(__file__).resolve().parent.parent

if str(AI_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(AI_SERVER_DIR))


def _import_main_module():
    """``main`` 을 부작용 격리 상태로 import 해 sys.modules 에 캐시한다.

    이미 import 돼 있으면 그대로 재사용한다. 한 번만 실행되며, 이후 check_*.py
    래퍼가 내부에서 다시 ``from main import ...`` 를 해도 캐시를 읽으므로
    추가 부작용이 없다.
    """

    if "main" in sys.modules:
        return sys.modules["main"]

    original_cwd = os.getcwd()
    saved_chroma_host = os.environ.pop("CHROMA_HOST", None)
    with tempfile.TemporaryDirectory(prefix="documind-pytest-chroma-") as workdir:
        os.chdir(workdir)
        try:
            import main  # noqa: F401  (import 부작용 격리가 목적)
        finally:
            os.chdir(original_cwd)
            if saved_chroma_host is not None:
                os.environ["CHROMA_HOST"] = saved_chroma_host
    return sys.modules["main"]


# 수집(collection) 단계에서 미리 안전하게 import 해 둔다. 이후 모든 테스트
# 모듈은 부작용 없이 ``import main`` / check_*.py import 를 쓸 수 있다.
_import_main_module()
