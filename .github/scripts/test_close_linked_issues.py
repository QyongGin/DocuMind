"""머지된 PR의 이슈 닫기 테스트. 실행: python -m unittest discover -s .github/scripts -p "test_*.py" """
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
