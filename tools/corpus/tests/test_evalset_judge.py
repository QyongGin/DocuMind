"""규칙 판정(결정 ②): 표기 맞추기, 숫자 경계, 맞음·일부·모름·틀림·애매·빈 답, 거절 문항, 지어낸 숫자."""

from evalset_data import item, refusal_item

from corpus.evalset.judge import contains, judge, normalize


def test_normalize_money_dates_and_commas():
    assert normalize("3만 원") == "30000원"
    assert normalize("1만 5천원") == "15000원"
    assert normalize("30,000원") == "30000원"
    assert normalize("2026. 9. 8.(월)") == "2026년9월8일(월)"
    assert normalize("9. 19.(금)") == "9월19일(금)"
    assert normalize("9월 8일") == "9월8일"
    assert normalize("평균 4.6등급") == "평균4.6등급"  # 소수는 날짜로 바꾸지 않는다


def test_contains_respects_number_boundaries():
    text = normalize("등록금은 130,000원입니다")
    assert not contains(text, "30,000원")
    assert contains(text, "130000원")
    assert contains(normalize("9월 8일에 시작"), "9. 8.(월)") is False  # 요일까지 적은 표기는 그대로 비교
    assert contains(normalize("9월 8일에 시작"), "9. 8.")


def test_value_answers():
    key = item("ev-0001")
    assert judge(key, "3만 원이에요")["label"] == "맞음"
    assert judge(key, "전형료는 30000원입니다.")["label"] == "맞음"
    wrong = judge(key, "25,000원이에요")
    assert (wrong["label"], wrong["forbidden_hits"]) == ("틀림", ["25,000원"])
    assert judge(key, "30,000원 또는 25,000원입니다")["label"] == "틀림"
    assert judge(key, "제공된 문서에서는 확인할 수 없습니다.")["label"] == "모름"
    assert judge(key, "확인할 수 없지만 30,000원으로 보입니다")["label"] == "애매"
    assert judge(key, "원서 접수 때 냅니다")["label"] == "애매"
    assert judge(key, "  ")["label"] == "빈 답"


def test_list_answers_can_be_partial():
    key = item("ev-0002", shape="목록", tags=["글 근거"], forbidden=[],
               facts=[{"name": "서류 1", "values": ["휴학원서"]}, {"name": "서류 2", "values": ["보호자 동의서"]}])
    assert judge(key, "휴학원서와 보호자 동의서를 냅니다")["label"] == "맞음"
    partial = judge(key, "휴학원서를 냅니다")
    assert (partial["label"], partial["missing"]) == ("일부", ["서류 2"])
    assert judge(key, "학생증을 냅니다")["label"] == "애매"


def test_date_written_differently_still_matches():
    key = item("ev-0003", forbidden=[], facts=[{"name": "시작일", "values": ["9. 8."]}])
    assert judge(key, "9월 8일에 시작합니다")["label"] == "맞음"


def test_numbers_not_in_context_are_flagged():
    key = item("ev-0004")
    flagged = judge(key, "전형료는 30,000원이고 면접료 5,000원이 따로 있습니다", context="전형료 30,000원")
    assert (flagged["label"], flagged["invented"]) == ("애매", ["5000원"])
    assert judge(key, "전형료는 30,000원입니다", context="전형료 30,000원")["label"] == "맞음"


def test_refusal_items():
    key = refusal_item("ev-0005")
    assert judge(key, "2028학년도 정원은 문서에서 확인할 수 없습니다.")["label"] == "맞음"
    assert judge(key, "2028학년도 정원은 40명입니다")["label"] == "틀림"  # 금지 값
    assert judge(key, "2028학년도 정원은 45명입니다")["label"] == "틀림"  # 답이 없는데 숫자를 단정
    assert judge(key, "2028은 확인할 수 없고, 2027학년도는 35명입니다")["label"] == "애매"
    assert judge(key, "아직 정해지지 않았어요")["label"] == "애매"
