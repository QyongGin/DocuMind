"""머지된 PR의 이슈 닫기 테스트. 실행: python -m unittest discover -s .github/scripts -p "test_*.py" """
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import close_linked_issues as closer  # noqa: E402


class ClosingIssuesTest(unittest.TestCase):
    def test_finds_closing_keywords_in_any_case_and_tense(self):
        body = "## 관련 이슈\n\nCloses #224\nfixes #3, Resolved #12\nclose #7 · Fixed: #8"
        self.assertEqual(closer.closing_issues(body), [3, 7, 8, 12, 224])

    def test_ignores_related_and_plain_mentions(self):
        body = "Related #225\n상위 이슈 #204의 하위 작업이다. #223, #224에서 이어진다."
        self.assertEqual(closer.closing_issues(body), [])

    def test_ignores_template_comment_example(self):
        body = "<!-- 이슈를 끝내면 Closes #12, 일부만 처리했으면 Related #13 -->\nCloses #229"
        self.assertEqual(closer.closing_issues(body), [229])

    def test_dedupes_reads_number_before_korean_particle_and_skips_inner_words(self):
        body = "Closes #5\nCloses #5\nencloses #6\nCloses #31을 닫는다"
        self.assertEqual(closer.closing_issues(body), [5, 31])

    def test_handles_empty_body(self):
        self.assertEqual(closer.closing_issues(""), [])
        self.assertEqual(closer.closing_issues(None), [])


SHA = "a" * 40


def pull(number, merged=True, sha=SHA, base="develop", body=""):
    return {"number": number, "merged_at": "2026-11-04T00:00:00Z" if merged else None, "merge_commit_sha": sha,
            "base": {"ref": base}, "body": body}


class MergedPrsTest(unittest.TestCase):
    def test_keeps_only_the_pr_merged_into_develop_by_this_commit(self):
        # 기본 브랜치에 없는 커밋이면 GitHub이 그 커밋을 담은 열린 PR도 돌려준다
        pulls = [pull(1), pull(2, merged=False), pull(3, base="main"), pull(4, sha="b" * 40)]
        self.assertEqual([found["number"] for found in closer.merged_prs(pulls, SHA)], [1])


class MainTest(unittest.TestCase):
    def run_main(self, responses):
        def fake_api(path):
            return responses[path]

        out = io.StringIO()
        env = {"REPO": "gana/docs", "COMMIT_SHA": SHA, "DRY_RUN": "1"}
        with mock.patch.dict(os.environ, env), mock.patch.object(closer, "gh_api", fake_api), redirect_stdout(out):
            code = closer.main()
        return code, out.getvalue()

    def test_reads_body_of_pr_merged_by_the_pushed_commit(self):
        responses = {f"repos/gana/docs/commits/{SHA}/pulls": [pull(240, body="Closes #229\nCloses #230\nRelated #225"),
                                                              pull(241, merged=False, body="Closes #300")],
                     "repos/gana/docs/issues/229": {"state": "open"},
                     "repos/gana/docs/issues/230": {"state": "closed"}}
        code, out = self.run_main(responses)
        self.assertEqual(code, 0)
        self.assertIn("#229: 닫을 예정", out)
        self.assertIn("#230: 건너뜀(closed)", out)
        self.assertNotIn("#300", out)  # 커밋을 담았을 뿐 머지되지 않은 PR의 본문은 읽지 않는다

    def test_commit_without_merged_pr_closes_nothing(self):
        code, out = self.run_main({f"repos/gana/docs/commits/{SHA}/pulls": []})
        self.assertEqual(code, 0)
        self.assertIn("머지한 PR 없음", out)


if __name__ == "__main__":
    unittest.main()
