# -*- coding: utf-8 -*-
import pytest
from services.sheets_reporter import _deduplicate_and_merge_report_rows, _classify_jira_records_contextually
from services.search import merged_records


def test_deduplicate_identical_rows():
    rows = [
        {
            '구분': '인증',
            '업무명': 'IP',
            '담당자': '비전정보통신 관리자',
            '세부 업무명': 'VSC-MB5000NC-S',
            '유형': '주간',
            '일자': '2026-11-05',
            '상세내용': 'VSC-MB5000NC-S',
            '진척(%)': '50',
            '상태': '진행중',
            '_source': 'jira',
            '_jira_key': 'VS-129',
        },
        {
            '구분': '인증',
            '업무명': 'IP',
            '담당자': '비전정보통신 관리자',
            '세부 업무명': 'VSC-MB5000NC-S',
            '유형': '주간',
            '일자': '2026-11-05',
            '상세내용': 'VSC-MB5000NC-S',
            '진척(%)': '50',
            '상태': '진행중',
            '_source': 'jira',
            '_jira_key': 'VS-131',
        }
    ]
    deduped = _deduplicate_and_merge_report_rows(rows)
    assert len(deduped) == 1
    assert deduped[0]['업무명'] == 'IP'
    assert deduped[0]['세부 업무명'] == 'VSC-MB5000NC-S'
    assert 'VS-129' in deduped[0]['_jira_key']
    assert 'VS-131' in deduped[0]['_jira_key']


def test_preserve_distinct_b2b_parent_projects():
    # In B2B, the same hardware model being certified under MAS vs KC are separate deliverables
    rows = [
        {
            '구분': '인증',
            '업무명': 'MAS',
            '담당자': '장욱재',
            '세부 업무명': 'VSC-MB5000NC-S',
            '유형': '주간',
            '일자': '2026-11-05',
            '상세내용': 'VSC-MB5000NC-S 파생모델 추가 (MAS)',
            '진척(%)': '50',
            '상태': '진행중',
            '_jira_key': 'VS-127',
        },
        {
            '구분': '인증',
            '업무명': 'KC',
            '담당자': '장욱재',
            '세부 업무명': 'VSC-MB5000NC-S',
            '유형': '주간',
            '일자': '2026-11-05',
            '상세내용': 'VSC-MB5000NC-S 파생모델 추가 (KC)',
            '진척(%)': '50',
            '상태': '진행중',
            '_jira_key': 'VS-128',
        }
    ]
    deduped = _deduplicate_and_merge_report_rows(rows)
    assert len(deduped) == 2
    task_names = [r['업무명'] for r in deduped]
    assert 'MAS' in task_names
    assert 'KC' in task_names


def test_merge_progressive_daily_comments_and_status():
    rows = [
        {
            '구분': '사업',
            '업무명': '감응형 무비젝터',
            '담당자': '홍성우',
            '세부 업무명': '감응형 무비젝터',
            '유형': '주간',
            '일자': '2026-10-27',
            '상세내용': '감응형 무비젝터\n[2026-10-27 홍성우] u볼트 제작',
            '진척(%)': '30',
            '상태': '진행중',
            '_jira_key': 'VS-110',
        },
        {
            '구분': '사업',
            '업무명': '감응형 무비젝터',
            '담당자': '홍성우',
            '세부 업무명': '감응형 무비젝터',
            '유형': '주간',
            '일자': '2026-10-28',
            '상세내용': '감응형 무비젝터\n[2026-10-28 홍성우] 설치 완료',
            '진척(%)': '100',
            '상태': '완료',
            '_jira_key': 'VS-112',
        }
    ]
    deduped = _deduplicate_and_merge_report_rows(rows)
    assert len(deduped) == 1
    m = deduped[0]
    assert m['일자'] == '2026-10-28'
    assert m['상태'] == '완료'
    assert m['진척(%)'] == '100'
    assert 'u볼트 제작' in m['상세내용']
    assert '설치 완료' in m['상세내용']


def test_parent_summary_preserved_in_contextual_classification():
    cfg = {"ai": {"enabled": False}}
    records = [
        {
            "title": "VSC-MB5000NC-S",
            "summary": "카메라 시험",
            "parentSummary": "MAS",
            "isSubtask": True,
            "startDate": "2026-11-01",
            "dueDate": "2026-11-10",
        }
    ]
    classified = _classify_jira_records_contextually(cfg, records)
    rid = id(records[0])
    assert rid in classified
    cat, task_name, r_type = classified[rid]
    assert task_name == "MAS"
