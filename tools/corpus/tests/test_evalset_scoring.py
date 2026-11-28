"""규칙 기반 채점(결정 ②): 표기 맞추기, 숫자 경계, 맞음·일부·모름·틀림·애매·빈 답, 답 없는 문항, 지어낸 숫자."""

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


def test_copied_evidence_row_is_not_a_forbidden_answer():
    """결론 뒤에 근거 표의 행을 그대로 옮겨 적으면 그 행의 옆 칸 값(금지 값)으로 '틀림'이 되지 않는다(#261)."""
    key = item("ev-0010")
    context = "[검색 근거]\n|구분|올해|지난해|\n|---|---|---|\n|전형료|30,000원|25,000원|"
    answer = "전형료는 30,000원입니다.\n\n<검색 근거>\n|구분|올해|지난해|\n| 전형료 | 30,000원 | 25,000원 |"
    copied = score(key, answer, context)
    assert (copied["label"], copied["forbidden_hits"]) == ("맞음", [])
    # 근거 글이 없으면 옮겨 적은 줄인지 모르므로 지금처럼 금지 값으로 본다
    assert score(key, answer)["label"] == "틀림"


def test_forbidden_value_outside_copied_rows_is_still_wrong():
    """근거 줄과 통째로 같지 않은 표 줄이나 문장으로 말한 금지 값은 그대로 '틀림'이다(#261)."""
    key = item("ev-0011")
    context = "|구분|올해|지난해|\n|전형료|30,000원|25,000원|"
    assert score(key, "|전형료|25,000원|", context)["label"] == "틀림"
    # 근거 행의 앞부분만 골라 적은 줄도 새로 쓴 단정이다
    earlier_first = "|구분|지난해|올해|\n|전형료|25,000원|30,000원|"
    assert score(key, "|전형료|25,000원|", earlier_first)["label"] == "틀림"
    rewritten = "전형료는 30,000원입니다.\n|전형료|30,000원|25,000원|\n다만 지난해 기준인 25,000원이 맞습니다."
    assert score(key, rewritten, context)["forbidden_hits"] == ["25,000원"]


def test_correct_value_only_in_copied_row_is_not_correct():
    """결론은 틀린 값인데 옮겨 적은 근거 행에만 정답 값이 있으면 '맞음'이 아니다(#261)."""
    key = item("ev-0012", forbidden=[])
    context = "|구분|올해|지난해|\n|전형료|30,000원|25,000원|"
    answer = "전형료는 20,000원입니다.\n|전형료|30,000원|25,000원|"
    result = score(key, answer, context)
    assert (result["label"], result["matched"]) == ("애매", [])


def test_facts_only_in_copied_rows_go_to_a_person():
    """근거 행을 그대로 옮겨 적은 것이 답 자체일 수 있어, 핵심 사실이 그 행에만 있으면 일부로 단정하지 않고 애매로 넘긴다(#261)."""
    key = item("ev-0013", shape="목록", tags=["표 근거"], forbidden=[],
               facts=[{"name": "목표 1", "values": ["문제 해결"]}, {"name": "목표 2", "values": ["직업기술"]}])
    context = "|교육목표 1|문제 해결 능력 배양|\n|교육목표 2|현장 직업기술 함양|"
    answer = "교육목표는 다음과 같습니다.\n|교육목표 1|문제 해결 능력 배양|\n|교육목표 2|현장 직업기술 함양|\n현장 직업기술을 키웁니다."
    result = score(key, answer, context)
    assert (result["label"], result["quoted_facts"]) == ("애매", ["목표 1"])
