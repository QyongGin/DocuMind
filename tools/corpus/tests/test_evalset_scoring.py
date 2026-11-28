"""규칙 기반 채점(결정 ②): 표기 맞추기, 숫자 경계, 맞음·일부·모름·틀림·애매·빈 답, 답 없는 문항, 지어낸 숫자."""

import pytest
from evalset_data import item, unanswerable_item

from corpus.evalset.scoring import contains, normalize, score


def test_normalize_money_dates_and_commas():
    assert normalize("3만 원") == "30000원"
    assert normalize("1만 5천원") == "15000원"
    assert normalize("30,000원") == "30000원"
    assert normalize("2026. 9. 8.(월)") == "2026년9월8일(월)"
    assert normalize("9. 19.(금)") == "9월19일(금)"
    assert normalize("9월 8일") == "9월8일"
    assert normalize("평균 4.6등급") == "평균4.6등급"  # 소수는 날짜로 바꾸지 않는다
    assert normalize("**3**만 원") == "30000원"  # 굵게 기호를 먼저 지워야 금액도 맞춰진다


def test_bold_marks_inside_value_still_match():
    """모델마다 굵게 쓰는 자리가 달라도 같은 답은 같게 채점한다(값만 굵게, 낱말마다 굵게)."""
    key = item("ev-0001")
    assert score(key, "전형료는 **30,000**원입니다.")["label"] == "맞음"
    listed = item("ev-0002", shape="목록", facts=[{"name": "보호자", "values": ["부·모"]}])
    assert score(listed, "학생의 **부**·**모** 모두 동의해야 합니다.")["label"] == "맞음"


def test_contains_respects_number_boundaries():
    text = normalize("등록금은 130,000원입니다")
    assert not contains(text, "30,000원")
    assert contains(text, "130000원")
    assert contains(normalize("9월 8일에 시작"), "9. 8.(월)") is False  # 요일까지 적은 표기는 그대로 비교
    assert contains(normalize("9월 8일에 시작"), "9. 8.")


def test_value_answers():
    key = item("ev-0001")
    assert score(key, "3만 원이에요")["label"] == "맞음"
    assert score(key, "전형료는 30000원입니다.")["label"] == "맞음"
    wrong = score(key, "25,000원이에요")
    assert (wrong["label"], wrong["forbidden_hits"]) == ("틀림", ["25,000원"])
    assert score(key, "30,000원 또는 25,000원입니다")["label"] == "틀림"
    assert score(key, "제공된 문서에서는 확인할 수 없습니다.")["label"] == "모름"
    assert score(key, "확인할 수 없지만 30,000원으로 보입니다")["label"] == "애매"
    assert score(key, "원서 접수 때 냅니다")["label"] == "애매"
    assert score(key, "  ")["label"] == "빈 답"


def test_list_answers_can_be_partial():
    key = item("ev-0002", shape="목록", tags=["글 근거"], forbidden=[],
               facts=[{"name": "서류 1", "values": ["휴학원서"]}, {"name": "서류 2", "values": ["보호자 동의서"]}])
    assert score(key, "휴학원서와 보호자 동의서를 냅니다")["label"] == "맞음"
    partial = score(key, "휴학원서를 냅니다")
    assert (partial["label"], partial["missing"]) == ("일부", ["서류 2"])
    assert score(key, "학생증을 냅니다")["label"] == "애매"


def test_date_written_differently_still_matches():
    key = item("ev-0003", forbidden=[], facts=[{"name": "시작일", "values": ["9. 8."]}])
    assert score(key, "9월 8일에 시작합니다")["label"] == "맞음"


def test_numbers_not_in_context_are_flagged():
    key = item("ev-0004")
    flagged = score(key, "전형료는 30,000원이고 면접료 5,000원이 따로 있습니다", context="전형료 30,000원")
    assert (flagged["label"], flagged["invented"]) == ("애매", ["5000원"])
    assert score(key, "전형료는 30,000원입니다", context="전형료 30,000원")["label"] == "맞음"


def test_unanswerable_items():
    key = unanswerable_item("ev-0005")
    assert score(key, "2028학년도 정원은 문서에서 확인할 수 없습니다.")["label"] == "맞음"
    assert score(key, "2028학년도 정원은 40명입니다")["label"] == "틀림"  # 금지 값
    assert score(key, "2028학년도 정원은 45명입니다")["label"] == "틀림"  # 답이 없는데 숫자를 단정
    assert score(key, "2028은 확인할 수 없고, 2027학년도는 35명입니다")["label"] == "애매"
    assert score(key, "아직 정해지지 않았어요")["label"] == "애매"


def test_guidance_facts_are_scored_separately():
    """ADR-0023: 맞는데 안내가 빠진 답은 정확 '맞음' + 안내 '부족'. 안내 사실은 정확 판정의 빠진 사실에 넣지 않는다."""
    key = item("ev-0006", question="가나대 휴학 중에 입대하면 어떻게 해요?", shape="절차", tags=["글 근거"], forbidden=[],
               facts=[{"name": "입대휴학 전환", "values": ["입대휴학"]},
                      {"name": "포털 신청", "values": ["포털"], "kind": "안내"},
                      {"name": "입영통지서", "values": ["입영통지서"], "kind": "안내"}])
    short = score(key, "입영이 확정되면 입대휴학으로 바꿀 수 있습니다")
    assert (short["label"], short["missing"], short["guidance"]["label"]) == ("맞음", [], "부족")
    half = score(key, "입대휴학으로 바꾸고 포털에서 신청합니다")
    assert (half["label"], half["guidance"]["label"], half["guidance"]["missing"]) == ("맞음", "일부", ["입영통지서"])
    full = score(key, "입영통지서를 챙겨 포털에서 입대휴학을 신청합니다")
    assert (full["label"], full["guidance"]["label"]) == ("맞음", "충족")
    assert score(key, "포털에 로그인하세요")["label"] == "애매"  # 핵심 없이 안내만 있으면 정확은 정하지 못한다
    assert score(key, "")["guidance"]["label"] == "부족"


def test_items_without_guidance_facts():
    assert score(item("ev-0001"), "3만 원이에요")["guidance"] == {"label": "해당 없음", "matched": [], "missing": []}


def test_refusal_appended_after_all_core_facts_is_correct():
    """핵심 사실을 다 말한 뒤 다른 것에 대해 '확인할 수 없다'를 덧붙인 답은 맞음(덧붙인 거절로 따로 셈).
    먼저 망설이고 값을 대는 답, 명사를 꾸미는 '확인할 수 없는'은 다르게 본다."""
    key = item("ev-0001")
    appended = score(key, "전형료는 30,000원입니다. 실기 추가 전형료는 문서에서 확인할 수 없습니다.")
    assert (appended["label"], appended["appended_refusal"], appended["abstained"]) == ("맞음", True, True)
    assert score(key, "확인할 수 없지만 30,000원으로 보입니다")["label"] == "애매"
    assert score(key, "문서에서 확인할 수 없습니다")["appended_refusal"] is False
    listed = item("ev-0002", shape="목록", forbidden=[],
                  facts=[{"name": "사진", "values": ["편집"]}, {"name": "날짜", "values": ["신청일자"]}])
    adnominal = score(listed, "편집한 사진, 확인할 수 없는 서류, 신청일자와 다른 문서는 반려됩니다")
    assert (adnominal["label"], adnominal["appended_refusal"]) == ("맞음", True)
    assert score(listed, "편집한 사진은 반려되고 나머지는 확인할 수 없습니다")["label"] == "애매"  # 핵심 하나 빠짐


def test_new_refusal_sentence_is_a_refusal():
    """2026-11-02부터의 운영 거절 문장(ADR-0050)도 거절로 본다. 옛 문장으로 낸 지난 실행 기록도 그대로 채점한다."""
    key = item("ev-0001")
    assert score(key, "학교 홈페이지 안내에서 찾지 못했습니다.")["label"] == "모름"
    assert score(unanswerable_item("ev-0009"), "학교 홈페이지 안내에서 찾지 못했습니다.")["label"] == "맞음"
    partial = score(key, "전형료는 30,000원입니다. 실기 추가 전형료는 학교 홈페이지 안내에서 찾지 못했습니다.")
    assert (partial["label"], partial["appended_refusal"]) == ("맞음", True)


def test_bare_table_number_in_context_is_not_invented():
    """표 칸에는 단위 없이 '50'만 있어도 답의 '50명'은 지어낸 숫자가 아니다. 다른 수(500)에 붙은 50은 아니다."""
    key = item("ev-0001", facts=[{"name": "정원", "values": ["50명"]}], forbidden=[])
    table = "|학과|정원|\n|자유전공학부|50|"
    assert score(key, "정원은 50명입니다.", table)["invented"] == []
    assert score(key, "정원은 50명입니다.", table)["label"] == "맞음"
    assert score(key, "정원은 50명입니다.", "|자유전공학부|500|")["invented"] == ["50명"]


def test_refusal_phrasings_seen_in_baseline():
    """베이스라인 답없음 거절 말투: '명시하고 있지 않습니다', '답변을 드리기 어렵습니다'."""
    key = unanswerable_item("ev-0009")
    assert score(key, "제공된 문서에서는 2028학년도 정원을 명시하고 있지 않습니다.")["label"] == "맞음"
    assert score(key, "정원에 대해 정확히 답변 드리기 어렵습니다. 입학팀에 문의하세요.")["label"] == "맞음"


# 표 읽기를 학습한 모델의 여러 행 답(ADR-0051 변경 메모): 확인 줄 다음 `결론:` 줄, 답 끝에 출처 번호
LARGEST = "가나대에서 정원이 가장 많은 학과는 어디예요?"
CHECKED_ROWS = "확인한 행:\n- 가나학과: 40명\n- 다라학과: 35명\n- 마바학과: 28명\n"


def largest_item(**extra) -> dict:
    fields = {"question": LARGEST, "facts": [{"name": "학과", "values": ["가나학과"]}],
              "forbidden": [{"value": "35명", "why": "옆 행 값"}]}
    return item("ev-0101", **{**fields, **extra})


def test_right_conclusion_is_not_wrong_for_forbidden_value_in_checked_rows():
    """결론이 맞으면 확인 줄에만 있는 금지 값(옆 행 35명)으로 틀림이 되지 않는다."""
    result = score(largest_item(), CHECKED_ROWS + "결론: 정원이 가장 많은 학과는 가나학과입니다.\n\n[출처 2]")
    assert (result["label"], result["forbidden_hits"], result["conclusion_only"]) == ("맞음", [], True)


def test_wrong_conclusion_is_not_right_for_answer_value_in_checked_rows():
    """결론이 틀리면 확인 줄에 정답 값(가나학과)이 있어도 맞음이 되지 않는다."""
    key = largest_item(forbidden=[])
    result = score(key, CHECKED_ROWS + "결론: 정원이 가장 많은 학과는 마바학과입니다.\n\n[출처 2]")
    assert (result["label"], result["matched"], result["conclusion_only"]) == ("애매", [], True)


@pytest.mark.parametrize("working", [
    CHECKED_ROWS,
    "근거 글: 2027학년도 학과별 모집 정원 표, 다라학과 35명\n",
    "고른 표: 학과별 모집 정원(다라학과 35명) [출처 2]\n",
])
def test_each_working_header_scores_the_conclusion(working):
    result = score(largest_item(), working + "결론: 가나학과입니다.\n\n[출처 2]")
    assert (result["label"], result["conclusion_only"]) == ("맞음", True)


def test_refusal_numbers_and_guidance_use_the_conclusion():
    """거절 판정, 지어낸 숫자, 안내 점수도 결론 부분으로 본다."""
    refused = score(unanswerable_item("ev-0102"), CHECKED_ROWS + "결론: 학교 홈페이지 안내에서 찾지 못했습니다.")
    assert (refused["label"], refused["abstained"], refused["conclusion_only"]) == ("맞음", True, True)
    rows_only_in_answer = score(largest_item(forbidden=[]), CHECKED_ROWS + "결론: 가나학과입니다.", context="가나학과")
    assert (rows_only_in_answer["label"], rows_only_in_answer["invented"]) == ("맞음", [])
    guided = largest_item(forbidden=[], facts=[{"name": "학과", "values": ["가나학과"]},
                                               {"name": "문의", "values": ["입학팀"], "kind": "안내"}])
    assert score(guided, "근거 글: 입학팀 모집 정원 안내\n결론: 가나학과입니다.")["guidance"]["label"] == "부족"
    assert score(guided, "근거 글: 모집 정원 안내\n결론: 가나학과입니다. 입학팀에 물어보세요.")["guidance"]["label"] == "충족"


@pytest.mark.parametrize("answer, label", [
    (CHECKED_ROWS + "정원이 가장 많은 학과는 가나학과입니다.", "틀림"),  # 확인 줄로 시작했는데 `결론:` 줄이 없음
    (CHECKED_ROWS + "결론:\n\n", "틀림"),  # 결론이 비었음
    ("다라학과는 35명입니다.\n결론: 가나학과입니다.", "틀림"),  # 확인 줄로 시작하지 않음
    ("정원이 가장 많은 학과는 가나학과이고 결론: 확인한 행: 없음", "맞음"),  # 본문 중간의 줄머리
])
def test_answers_outside_the_contract_are_scored_whole(answer, label):
    """약속에 맞지 않는 답은 지금처럼 답 전체로 매긴다."""
    result = score(largest_item(), answer)
    assert (result["label"], result["conclusion_only"]) == (label, False)


def test_plain_answers_are_not_marked_conclusion_only():
    assert score(item("ev-0001"), "전형료는 30,000원입니다.")["conclusion_only"] is False
    assert score(item("ev-0001"), "")["conclusion_only"] is False
