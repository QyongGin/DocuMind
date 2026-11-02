"""PR 규칙 검사 테스트. 실행: python -m unittest discover -s .github/scripts -p "test_*.py" """
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_pr_rules as rules  # noqa: E402

SCRIPT = Path(__file__).parent / "check_pr_rules.py"


class TitleTest(unittest.TestCase):
    def test_accepts_type_scope_summary(self):
        for title in ("feat(corpus): 학습 예시를 만든다", "docs(workflow): PR 규칙을 적는다", "chore(release): 2026-11 릴리스"):
            self.assertIsNone(rules.title_problem(title), title)

    def test_rejects_missing_scope_unknown_type_or_empty_summary(self):
        for title in ("feat: 범위 없음", "Feat(ai): 대문자 type", "update(ai): 모르는 type", "fix(ai):", "fix(ai) : 띄어 씀",
                      "학습 예시 도구"):
            self.assertIsNotNone(rules.title_problem(title), title)


class IssueLinkTest(unittest.TestCase):
    def test_accepts_closes_or_related_with_number(self):
        for body in ("## 관련 이슈\n\nCloses #190\n", "Related #189(AI 서버 요청 칸은 #194)", "fixes #3"):
            self.assertIsNone(rules.issue_problem(body), body)

    def test_rejects_template_placeholder_comment_example_and_none(self):
        template = "## 관련 이슈\n\n<!-- 이슈를 끝내면 Closes #번호 -->\nCloses #\n"
        for body in (template, "<!-- Closes #12 -->", "## 관련 이슈\n\n없음", "", "#189 참고"):
            self.assertIsNotNone(rules.issue_problem(body), body)


class WarningTest(unittest.TestCase):
    def test_branch_without_issue_number_warns(self):
        self.assertIsNotNone(rules.branch_warning("feat/m2-s6-method-review"))
        for branch in ("chore/#196-pr-rules-ci", "develop", "release/2026-11-03"):
            self.assertIsNone(rules.branch_warning(branch), branch)

    def test_code_lines_skip_docs_lockfiles_and_binaries(self):
        numstat = "\n".join(["600\t10\ttools/corpus/corpus/trainset/plan.py",
                             "900\t0\tdocs/rag/m2/보고서.md",
                             "5000\t0\tfrontend/package-lock.json",
                             "-\t-\tdocs/그림.png",
                             "300\t100\ttools/corpus/tests/test_plan.py"])
        self.assertEqual(rules.code_lines(numstat), 1010)
        self.assertIsNotNone(rules.size_warning(1010))
        self.assertIsNone(rules.size_warning(1000))


class MainTest(unittest.TestCase):
    def run_script(self, **env):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                env={**os.environ, "BASE_SHA": "", **env})
        return result.returncode, result.stdout

    def test_fails_with_error_lines_when_rules_are_broken(self):
        code, out = self.run_script(PR_TITLE="학습 예시 도구", PR_BODY="없음", HEAD_REF="feat/no-issue")
        self.assertEqual(code, 1)
        self.assertEqual(out.count("::error"), 2)
        self.assertIn("::warning", out)

    def test_passes_with_title_and_issue_link(self):
        code, out = self.run_script(PR_TITLE="chore(ci): PR 규칙을 검사한다", PR_BODY="Closes #196",
                                    HEAD_REF="chore/#196-pr-rules-ci")
        self.assertEqual(code, 0)
        self.assertNotIn("::error", out)


if __name__ == "__main__":
    unittest.main()
