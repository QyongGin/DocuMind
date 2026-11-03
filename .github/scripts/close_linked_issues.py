"""develop에 머지된 PR이 본문에 닫는 말로 적은 이슈를 닫는다(CONTRIBUTING.md 6장).

기본 브랜치가 main이라 develop에 머지한 PR의 `Closes #번호`로는 GitHub이 이슈를 닫지 않는다. 그래서 머지된 PR 본문에서
`Closes`·`Fixes`·`Resolves`(과거형 포함) 뒤의 번호를 찾아 열린 이슈만 코멘트와 함께 닫는다.
`Related #번호`, 템플릿 주석 안의 예시, PR 번호, 이미 닫힌 이슈는 건드리지 않는다.
환경 변수: PR_BODY, PR_NUMBER, REPO(owner/name), GH_TOKEN. DRY_RUN=1이면 닫지 않고 할 일만 출력한다.
"""
import json
import os
import re
import subprocess
import sys

# 번호 뒤에 한글 조사가 바로 붙어도("Closes #31을") 찾도록 번호 끝에는 경계를 두지 않는다
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)", re.IGNORECASE)


def closing_issues(body: str) -> list[int]:
    """본문에서 닫는 말 뒤의 이슈 번호를 작은 순서로 돌려준다. 템플릿 주석 안의 예시는 세지 않는다."""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    return sorted({int(number) for number in CLOSING.findall(text)})


def issue_state(repo: str, number: int) -> tuple[str, bool]:
    """(상태, PR인지)를 돌려준다. 이슈 API는 PR도 이슈로 돌려주므로 pull_request 칸으로 가른다."""
    out = subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}"], check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    return data["state"], "pull_request" in data


def main() -> int:
    repo, pr_number = os.environ["REPO"], os.environ["PR_NUMBER"]
    dry_run = os.environ.get("DRY_RUN") == "1"
    numbers = closing_issues(os.environ.get("PR_BODY", ""))
    if not numbers:
        print("닫을 이슈 없음")
        return 0
    failed = 0
    for number in numbers:
        try:
            state, is_pr = issue_state(repo, number)
        except subprocess.CalledProcessError as error:
            print(f"#{number}: 찾지 못함({error.stderr.strip()})")
            failed += 1
            continue
        if is_pr or state != "open":
            print(f"#{number}: 건너뜀({'PR' if is_pr else state})")
            continue
        if dry_run:
            print(f"#{number}: 닫을 예정")
            continue
        subprocess.run(["gh", "issue", "close", str(number), "--repo", repo,
                        "--comment", f"#{pr_number}이 develop에 머지되어 닫습니다."], check=True)
        print(f"#{number}: 닫음")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
