"""Regression tests for notification identity/read-state fixes.

These cover issues that are easy to reintroduce because they depend on
display-name conventions and on the difference between direct and shared
(broadcast/role) notifications.
"""
import queue

from db import get_one, query
from services.auth import (
    create_user,
    hash_password,
    user_can_access_notification,
)
from services.notification_service import (
    _is_same_user,
    add_notification,
    get_user_notifications,
    mark_notification_as_read,
    subscribe_notifications,
    trigger_task_assigned_notification,
    unsubscribe_notifications,
    _NOTIF_SUBSCRIBERS,
)


def _mk_user(name, username, email, role="member", dept="dev"):
    salt, pwd = hash_password("TestPass123!")
    return create_user(name, username, dept, email, salt, pwd, role=role)


def test_base_name_fallback_does_not_leak_between_distinct_accounts(tmp_db):
    lead = _mk_user("김철수 팀장", "audit_lead", "audit_lead@test.local", role="manager")
    member = _mk_user("김철수", "audit_member", "audit_member@test.local")
    # This name is addressed to the member only. The lead's display name has a
    # title suffix whose base equals the member's name.
    add_notification(
        recipient_email="",
        recipient_name="김철수",
        sender_name="system",
        title="ONLY-MEMBER",
        content="secret",
    )

    lead_rows = get_user_notifications(
        user_email=lead["email"], user_name=lead["name"], is_admin=False
    )
    member_rows = get_user_notifications(
        user_email=member["email"], user_name=member["name"], is_admin=False
    )
    assert "ONLY-MEMBER" not in [r["title"] for r in lead_rows]
    assert "ONLY-MEMBER" in [r["title"] for r in member_rows]

    row = get_one("SELECT * FROM notifications WHERE title = 'ONLY-MEMBER'")
    assert user_can_access_notification(lead, row) is False
    assert user_can_access_notification(member, row) is True


def test_email_addressed_notification_is_not_visible_by_name(tmp_db):
    lead = _mk_user("Audit Lead", "audit_lead2", "audit_lead2@test.local")
    member = _mk_user("Audit Member", "audit_member2", "audit_member2@test.local")
    notif_id = add_notification(
        recipient_email=lead["email"],
        recipient_name=member["name"],
        sender_name="system",
        title="EMAIL-LEAD-NAME-MEMBER",
        content="secret",
    )
    row = get_one("SELECT * FROM notifications WHERE id = ?", (notif_id,))

    assert user_can_access_notification(lead, row) is True
    assert user_can_access_notification(member, row) is False
    member_rows = get_user_notifications(
        user_email=member["email"], user_name=member["name"], is_admin=False
    )
    assert "EMAIL-LEAD-NAME-MEMBER" not in [r["title"] for r in member_rows]


def test_is_same_user_keeps_title_suffix_accounts_separate():
    assert _is_same_user("홍길동 팀장", "홍길동") is False
    assert _is_same_user("홍길동", "홍길동") is True


def test_email_addressed_notification_survives_duplicate_display_name(tmp_db):
    first = _mk_user("Duplicate Name", "dup_name_1", "dup1@test.local", dept="dept_a")
    second = _mk_user("Duplicate Name", "dup_name_2", "dup2@test.local", dept="dept_b")
    add_notification(
        recipient_email=second["email"],
        recipient_name=second["name"],
        sender_name=first["name"],
        title="SAME-NAME-EMAIL",
        content="this is for the second user",
    )
    second_rows = get_user_notifications(
        user_email=second["email"], user_name=second["name"], is_admin=False
    )
    assert "SAME-NAME-EMAIL" in [r["title"] for r in second_rows]


def test_assignment_between_duplicate_names_uses_email(tmp_db):
    first = _mk_user("Same Name", "same_name_1", "same_name_1@test.local", dept="dept_a")
    second = _mk_user("Same Name", "same_name_2", "same_name_2@test.local", dept="dept_b")
    trigger_task_assigned_notification(
        record_id="AUDIT-1",
        title="Duplicated account names",
        author_name=first["name"],
        assignee_name=second["name"],
        assignee_email=second["email"],
        author_email=first["email"],
    )
    rows = query(
        "SELECT recipient_email FROM notifications WHERE title = '새 업무가 배정되었습니다'"
    )
    assert [r["recipient_email"] for r in rows] == [second["email"]]


def test_empty_recipient_is_not_an_implicit_broadcast(tmp_db):
    assert add_notification(
        recipient_email="",
        recipient_name="",
        sender_name="system",
        title="ORPHAN",
        content="must not be broadcast",
    ) is None
    assert query("SELECT COUNT(*) AS c FROM notifications")[0]["c"] == 0


def test_shared_broadcast_read_state_does_not_clear_for_everyone(tmp_db):
    lead = _mk_user("Read Lead", "read_lead", "read_lead@test.local")
    member = _mk_user("Read Member", "read_member", "read_member@test.local")
    notif_id = add_notification(
        recipient_email="all",
        recipient_name="",
        sender_name="system",
        title="BROADCAST-READ",
        content="hello",
    )
    lead_rows = get_user_notifications(
        user_email=lead["email"], user_name=lead["name"], is_admin=False
    )
    assert any(r["id"] == notif_id and r["is_read"] is False for r in lead_rows)

    mark_notification_as_read(notif_id)

    # The shared row must not be flipped globally. Both users still get the
    # per-browser read state; this test only asserts the DB is untouched.
    assert get_one("SELECT is_read FROM notifications WHERE id = ?", (notif_id,))["is_read"] == 0
    member_rows = get_user_notifications(
        user_email=member["email"], user_name=member["name"], is_admin=False
    )
    assert any(r["id"] == notif_id and r["is_read"] is False for r in member_rows)


def test_sse_queue_overflow_keeps_subscriber_and_newest_event(tmp_db):
    q = queue.Queue(maxsize=1)
    subscribe_notifications(q, {"email": "queue@test.local", "name": "Queue User"})
    try:
        add_notification(
            recipient_email="queue@test.local",
            recipient_name="Queue User",
            sender_name="system",
            title="first",
            content="one",
        )
        add_notification(
            recipient_email="queue@test.local",
            recipient_name="Queue User",
            sender_name="system",
            title="second",
            content="two",
        )
        assert q.qsize() == 1
        event = q.get_nowait()
        assert event["data"]["title"] == "second"
        assert q in _NOTIF_SUBSCRIBERS
    finally:
        unsubscribe_notifications(q)
