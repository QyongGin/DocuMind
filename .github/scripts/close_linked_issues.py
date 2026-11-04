"""develop에 머지된 PR이 본문에 닫는 말로 적은 이슈를 닫는다(CONTRIBUTING.md 6장).

기본 브랜치가 main이라 develop에 머지한 PR의 `Closes #번호`로는 GitHub이 이슈를 닫지 않는다. 그래서 develop에 들어온
커밋을 머지한 PR을 찾아, 본문에서 `Closes`·`Fixes`·`Resolves`(과거형 포함) 뒤의 번호를 찾고 열린 이슈만 코멘트와 함께 닫는다.
`Related #번호`, 템플릿 주석 안의 예시, PR 번호, 이미 닫힌 이슈는 건드리지 않는다.
환경 변수: COMMIT_SHA, REPO(owner/name), GH_TOKEN. DRY_RUN=1이면 닫지 않고 할 일만 출력한다.
"""
import json
import os
import re
import subprocess
import sys

BASE = "develop"
# 번호 뒤에 한글 조사가 바로 붙어도("Closes #31을") 찾도록 번호 끝에는 경계를 두지 않는다
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)", re.IGNORECASE)


def closing_issues(body: str) -> list[int]:
    """본문에서 닫는 말 뒤의 이슈 번호를 작은 순서로 돌려준다. 템플릿 주석 안의 예시는 세지 않는다."""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    return sorted({int(number) for number in CLOSING.findall(text)})


def merged_prs(pulls: list[dict], sha: str, base: str = BASE) -> list[dict]:
    """커밋에 연결된 PR 중 그 커밋으로 base에 머지된 PR. 기본 브랜치에 없는 커밋이면 GitHub이 그 커밋을 담은 열린 PR도
    함께 돌려주므로, 머지됐고 머지 커밋이 이 커밋인 PR만 남긴다."""
    return [pull for pull in pulls if pull.get("merged_at") and pull.get("merge_commit_sha") == sha
            and (pull.get("base") or {}).get("ref") == base]


def gh_api(path: str):
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def issue_state(repo: str, number: int) -> tuple[str, bool]:
    """(상태, PR인지)를 돌려준다. 이슈 API는 PR도 이슈로 돌려주므로 pull_request 칸으로 가른다."""
    data = gh_api(f"repos/{repo}/issues/{number}")
    return data["state"], "pull_request" in data


def main() -> int:
    repo, sha = os.environ["REPO"], os.environ["COMMIT_SHA"]
    dry_run = os.environ.get("DRY_RUN") == "1"
    pulls = merged_prs(gh_api(f"repos/{repo}/commits/{sha}/pulls"), sha)
    if not pulls:
        print(f"{sha[:7]}: {BASE}에 머지한 PR 없음")
        return 0
    failed = 0
    for pull in pulls:
        numbers = closing_issues(pull.get("body") or "")
        print(f"#{pull['number']}: 닫는 말로 적은 이슈 {numbers or '없음'}")
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
                            "--comment", f"#{pull['number']}이 {BASE}에 머지되어 닫습니다."], check=True)
            print(f"#{number}: 닫음")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
