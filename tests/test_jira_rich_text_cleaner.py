import pytest
from utils.text import clean_jira_rich_text

def test_clean_jira_rich_text_empty_and_plain():
    assert clean_jira_rich_text("") == ""
    assert clean_jira_rich_text(None) is None
    assert clean_jira_rich_text("일반 텍스트 변경: A ➔ B") == "일반 텍스트 변경: A ➔ B"

def test_clean_jira_rich_text_full_adf_table_and_panels():
    raw = (
        "완료 처리내용: h2. 🔎 현장점검 보고 {panel:bgColor=#deebff} {{2026-11-03}} 1차 현장점검 요약입니다. {panel}\n"
        '{adf:display=block} {"type":"table","attrs":{"isNumberColumnEnabled":true},"content":['
        '{"type":"tableRow","content":[{"type":"tableHeader","content":[{"type":"paragraph","content":[{"type":"text","text":"항목"}]}]},{"type":"tableHeader","content":[{"type":"paragraph","content":[{"type":"text","text":"상태 / 내용"}]}]}]},'
        '{"type":"tableRow","content":[{"type":"tableCell","content":[{"type":"paragraph","content":[{"type":"text","text":"전원어뎁터"}]}]},{"type":"tableCell","content":[{"type":"paragraph","content":[{"type":"text","text":"정상"}]}]}]},'
        '{"type":"tableRow","content":[{"type":"tableCell","content":[{"type":"paragraph","content":[{"type":"text","text":"카메라"}]}]},{"type":"tableCell","content":[{"type":"paragraph","content":[{"type":"text","text":"고장 - 철거 후 수리접수"}]}]}]}'
        "]} {adf} 11/09 단종모델 수리불가[^수리불가확인서.pdf] [^사진대지.pdf]"
    )
    res = clean_jira_rich_text(raw)
    assert "{adf" not in res
    assert "{panel" not in res
    assert "h2." not in res
    assert "🔎 현장점검 보고" in res
    assert "2026-11-03 1차 현장점검 요약입니다." in res
    assert "전원어뎁터: 정상" in res
    assert "카메라: 고장 - 철거 후 수리접수" in res
    assert "📎 수리불가확인서.pdf" in res
    assert "📎 사진대지.pdf" in res
