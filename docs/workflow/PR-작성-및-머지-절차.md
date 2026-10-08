# PR 작성·머지 절차

> 이 저장소의 모든 PR에 적용한다 (2026-09-30 확정, #112~#114에서 이 방식으로 진행).
> 요약 규칙은 루트 `AGENTS.md`의 "커밋·PR 작성" 절에 있고, 이 문서는 단계별 절차다.

## 1. 커밋

- 메시지는 `type(scope): 요약` 형식이다. type은 `CONTRIBUTING.md` 5장을 따른다.
- **AI 서명을 넣지 않는다.** `Co-Authored-By: Claude`, "Generated with Claude Code" 같은 줄이 해당한다.
- 성격이 다른 변경은 커밋을 나눈다. 예: 브랜치 병합과 충돌 해결 / 주석 정리 / 테스트 추가.

## 2. PR을 올리기 전 확인

| 확인 | 방법 |
|---|---|
| 테스트 | 바뀐 모듈의 테스트 실행 (ai-server: `ai-server/venv/bin/python -m pytest -q`) |
| 공백 오류 | `git diff --check origin/develop...HEAD` |
| AI 서명 | `git log origin/develop..HEAD --format=%B \| grep -c 'Co-Authored-By'` 결과가 0 |
| 다른 브랜치를 합친 경우 | 합친 결과를 다시 컴파일하고 테스트한다. **git의 "자동 병합 성공"은 코드가 맞다는 뜻이 아니다.** 같은 기능이 두 브랜치의 다른 위치에 있으면 둘 다 들어간다 |
| 새 동작에 테스트를 붙인 경우 | 가능하면 동작을 일부러 되돌려 보고 테스트가 실패하는지 확인한다 (변이 확인). **반드시 커밋한 뒤에 하고, 되돌리기는 바꾼 그 파일에만 한다**(`git checkout -- <파일>`). 커밋 전에 폴더째 되돌리면 아직 커밋하지 않은 수정까지 지워진다(2026-10-02 #126에서 겪음) |

## 3. PR 초안

- **제목**: `type(scope): 요약`. 이슈 번호는 넣지 않는다.
- **본문**: `.github/PULL_REQUEST_TEMPLATE.md`의 다섯 섹션(관련 이슈, 배경, 변경 내용, 확인한 내용, 주의할 점)만 쓴다. 템플릿의 HTML 주석은 지운다. 이모지와 AI 서명은 넣지 않는다.
- **관련 이슈**: 이슈의 완료 조건을 모두 만족하면 `Closes #번호`, 일부만 처리하면 `Related #번호`.
- 초안(제목, 브랜치, 본문 전문)을 **사용자에게 먼저 보여준다.** 이때 아래 중 하나를 고르게 한다.
  - 올리고 바로 머지
  - 올리기만 (머지는 사용자가 확인 후 결정)
  - 초안 수정

## 4. 올리기와 머지 (사용자 승인 후)

```bash
gh pr create --base develop --head <브랜치> --title "<제목>" --body-file <본문 파일>
```

머지까지 승인받았으면, 로컬에서 `develop`으로 먼저 전환한 뒤 squash 머지한다.

```bash
gh pr merge <PR번호> --squash --subject "<제목> (#<PR번호>)" --body "" --delete-branch
```

- 머지 커밋 제목은 `PR 제목 (#PR번호)`다. 이슈 번호가 아니라 PR 번호다.
- 본문은 비운다. 비우지 않으면 PR 안의 커밋 메시지가 목록으로 붙는다. 상세 내용은 PR 페이지에 남는다.
- 머지한 브랜치는 삭제한다.

머지 후에는 로컬 `develop`을 최신화하고 테스트를 한 번 돌린다.

```bash
git pull --ff-only origin develop
```

## 5. 릴리스 PR (`develop → main`)

일반 PR과 두 가지가 다르다 (2026-09-30 #120에서 확정).

- **merge commit으로 머지한다.** squash로 합치면 main에 develop에 없는 커밋이 생겨 두 브랜치의 기록이 끊기고, 다음 릴리스 때 충돌이 날 수 있다.
- **develop을 절대 삭제하지 않는다.** `--delete-branch`를 쓰지 않는다. #120에서 저장소의 "머지 후 브랜치 자동 삭제" 설정 때문에 develop이 지워진 적이 있어, 2026-09-30에 이 설정을 끄고 develop에 삭제·강제 푸시 금지 규칙(ruleset `develop`)을 걸었다. 그래도 머지 직후 `git ls-remote --heads origin develop`으로 남아 있는지 확인한다. 지워졌으면 로컬 develop으로 바로 되살린다(`git push origin develop:refs/heads/develop`).
- 자동 삭제 설정을 껐으므로 일반 PR의 기능 브랜치는 머지 명령의 `--delete-branch`로 지운다(4장).

```bash
gh pr create --base main --head develop --title "chore(release): <요약>" --body-file <본문 파일>
gh pr merge <PR번호> --merge --subject "chore(release): <요약> (#<PR번호>)" --body ""
```

## 6. 이슈 닫기

- 기본 브랜치가 `main`이라서, `develop`에 머지한 PR의 `Closes #번호`로는 이슈가 자동으로 닫히지 않는다.
- `develop → main` 릴리스 PR 본문에 그동안 머지된 이슈를 `Closes #번호`로 모아 적는다. `main`에 머지될 때 한꺼번에 닫힌다.
- 머지 후 이슈가 실제로 닫혔는지 확인한다. PR을 만든 직후 `gh pr view <번호> --json closingIssuesReferences`로 연결을 먼저 확인한다.
- **이 저장소에서는 main 대상 릴리스 PR에서도 `Closes`가 연결되지 않았다** (#120의 `Closes #111`, #122의 `Closes #18`, 2회 연속). 본문 바이트는 정상이었고 본문을 다시 저장해도 연결되지 않았으며, API로 보이는 저장소 설정에서도 원인을 찾지 못했다. 그래서 릴리스를 머지한 뒤 이슈를 코멘트와 함께 직접 닫는 것을 기본으로 한다.

```bash
gh issue close <번호> --comment "#<develop PR>로 develop에 반영됐고, #<릴리스 PR>로 main에 릴리스되어 닫습니다."
```

- 마일스톤의 열린 이슈가 0개가 되면 마일스톤도 닫는다: `gh api -X PATCH repos/QyongGin/DocuMind/milestones/<번호> -f state=closed`

## 7. 되돌릴 수 없는 작업

- force-push는 **머지 전 개인 브랜치**에서만 하고, `--force-with-lease=<브랜치>:<예상 커밋>`으로 원격이 예상한 상태일 때만 덮어쓴다.
- 공용 브랜치(`main`, `develop`)의 기록은 다시 쓰지 않는다. 커밋 번호가 연쇄로 바뀌어 PR 링크와 태그가 어긋난다.
