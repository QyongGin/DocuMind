"""PR 규칙 검사(CONTRIBUTING.md 0·2·6장).

제목 형식과 본문의 이슈 연결이 없으면 실패하고, 바뀐 코드가 많거나 브랜치 이름에 이슈 번호가 없으면 경고만 한다.
환경 변수: PR_TITLE, PR_BODY, HEAD_REF, BASE_SHA(없으면 크기 검사를 건너뛴다).
"""
import os
import re
import subprocess
import sys

TYPES = ("feat", "fix", "refactor", "test", "docs", "chore")
TITLE = re.compile(rf"^({'|'.join(TYPES)})\([^()\s][^()]*\): \S")
ISSUE_LINK = re.compile(r"\b(closes|fixes|resolves|related)\s+#\d+", re.IGNORECASE)
MAX_CODE_LINES = 1000
# 코드 크기에서 빼는 파일: 문서와 의존성 잠금 파일(사람이 읽고 리뷰하는 코드가 아님)
NOT_CODE = (".md", "package-lock.json")
GUIDE = "CONTRIBUTING.md 2장·6장"


def title_problem(title: str) -> str | None:
    """제목이 `type(scope): 요약`이 아니면 문제 설명을 돌려준다."""
    if TITLE.match(title.strip()):
        return None
    return f"PR 제목이 'type(scope): 요약' 형식이 아니다(type: {', '.join(TYPES)}). 지금 제목: {title!r}"


def issue_problem(body: str) -> str | None:
    """본문에 `Closes #번호`·`Related #번호` 같은 이슈 연결이 없으면 문제 설명을 돌려준다. 템플릿 주석 안의 예시는 세지 않는다."""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    if ISSUE_LINK.search(text):
        return None
    return "PR 본문에 이슈 연결(`Closes #번호` 또는 `Related #번호`)이 없다. 작업은 이슈부터 시작한다."


def branch_warning(head_ref: str) -> str | None:
    """브랜치 이름에 이슈 번호(`#12`)가 없으면 경고 설명을 돌려준다. 릴리스 PR의 develop·release 브랜치는 뺀다."""
    if head_ref in ("develop", "main") or head_ref.startswith("release/") or re.search(r"#\d+", head_ref):
        return None
    return f"브랜치 이름에 이슈 번호가 없다({head_ref}). 예: feat/#12-설명(CONTRIBUTING.md 4장)."


def code_lines(numstat: str) -> int:
    """`git diff --numstat` 출력에서 문서·잠금 파일·바이너리를 뺀 추가+삭제 줄 수."""
    total = 0
    for line in numstat.splitlines():
        added, deleted, path = line.split("\t", 2)
        if added == "-" or path.endswith(NOT_CODE):
            continue
        total += int(added) + int(deleted)
    return total


def size_warning(lines: int) -> str | None:
    """바뀐 코드가 기준을 넘으면 경고 설명을 돌려준다."""
    if lines <= MAX_CODE_LINES:
        return None
    return (f"바뀐 코드가 {lines}줄이다({MAX_CODE_LINES}줄 초과). 한 가지 목적의 변경인지 확인하고, "
            "나눌 수 없으면 본문 '주의할 점'에 이유를 적는다.")


def main() -> int:
    errors = [problem for problem in (title_problem(os.environ.get("PR_TITLE", "")),
                                      issue_problem(os.environ.get("PR_BODY", ""))) if problem]
    warnings = [branch_warning(os.environ.get("HEAD_REF", ""))]
    base = os.environ.get("BASE_SHA")
    if base:
        numstat = subprocess.run(["git", "diff", "--numstat", f"{base}...HEAD"], capture_output=True, text=True,
                                 check=True).stdout
        warnings.append(size_warning(code_lines(numstat)))
    for warning in filter(None, warnings):
        print(f"::warning title=PR 규칙::{warning}")
    for error in errors:
        print(f"::error title=PR 규칙::{error} ({GUIDE})")
    if not errors:
        print("PR 규칙 통과")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
