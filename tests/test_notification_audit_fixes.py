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
        user_email=lead["email"], user_name=lead["name"], is_admin=False, user_id=lead["id"]
    )
    assert any(r["id"] == notif_id and r["is_read"] is False for r in lead_rows)

    mark_notification_as_read(notif_id, user_id=lead["id"])

    # The shared row must not be flipped globally, but the lead's own read row
    # must make it read for the lead only.
    assert get_one("SELECT is_read FROM notifications WHERE id = ?", (notif_id,))["is_read"] == 0
    assert query(
        "SELECT 1 FROM notification_reads WHERE notification_id = ? AND user_id = ?",
        (notif_id, lead["id"])
    )
    lead_rows = get_user_notifications(
        user_email=lead["email"], user_name=lead["name"], is_admin=False, user_id=lead["id"]
    )
    assert any(r["id"] == notif_id and r["is_read"] is True for r in lead_rows)
    member_rows = get_user_notifications(
        user_email=member["email"], user_name=member["name"], is_admin=False, user_id=member["id"]
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


def test_cleanup_old_notifications_removes_expired_rows_and_reads(tmp_db):
    from services.notification_service import cleanup_old_notifications
    from db import execute
    u = _mk_user("Retention User", "retention_u", "retention@test.local")
    nid = add_notification(
        recipient_email=u["email"],
        recipient_name=u["name"],
        sender_name="system",
        title="EXPIRED-NOTIF",
        content="should be purged",
        created_at="2020-01-01 10:00:00",
    )
    mark_notification_as_read(nid, user_id=u["id"])
    assert query("SELECT 1 FROM notifications WHERE id = ?", (nid,))
    assert query("SELECT 1 FROM notification_reads WHERE notification_id = ?", (nid,))

    cleanup_old_notifications(days=30)
    assert not query("SELECT 1 FROM notifications WHERE id = ?", (nid,))
    assert not query("SELECT 1 FROM notification_reads WHERE notification_id = ?", (nid,))


def test_pagination_and_unread_count(tmp_db):
    from services.notification_service import count_unread_notifications
    u = _mk_user("Page User", "page_u", "page@test.local")
    ids = []
    for i in range(15):
        nid = add_notification(
            recipient_email=u["email"],
            recipient_name=u["name"],
            sender_name="system",
            title=f"PAGE-NOTIF-{i:02d}",
            content=f"content {i}",
            created_at=f"2026-11-01 10:{i:02d}:00",
        )
        ids.append(nid)

    assert count_unread_notifications(user_email=u["email"], user_name=u["name"], user_id=u["id"]) == 15

    page1 = get_user_notifications(user_email=u["email"], user_name=u["name"], limit=5, offset=0, user_id=u["id"])
    assert len(page1) == 5

    page2 = get_user_notifications(user_email=u["email"], user_name=u["name"], limit=5, offset=5, user_id=u["id"])
    assert len(page2) == 5

    # Distinct pages
    p1_ids = {r["id"] for r in page1}
    p2_ids = {r["id"] for r in page2}
    assert p1_ids.isdisjoint(p2_ids)


def test_trigger_status_changed_and_participants_added(tmp_db):
    from services.notification_service import (
        trigger_status_changed_notification,
        trigger_participants_added_notification,
    )
    assignee = _mk_user("Worker", "worker_u", "worker@test.local")
    author = _mk_user("Manager", "manager_u", "manager@test.local", role="manager")
    p1 = _mk_user("Helper One", "helper1_u", "helper1@test.local")

    # 1. Status change trigger
    trigger_status_changed_notification(
        record_id="CARD-100",
        title="Card 100 Title",
        author_name=author["name"],
        old_status="진행",
        new_status="완료",
        assignee_name=assignee["name"],
        assignee_email=assignee["email"],
        author_email=author["email"],
    )
    notifs = get_user_notifications(user_email=assignee["email"], user_name=assignee["name"], user_id=assignee["id"])
    assert any("업무 상태가 변경되었습니다" in r["title"] for r in notifs)

    # 2. Participants added trigger
    trigger_participants_added_notification(
        record_id="CARD-100",
        title="Card 100 Title",
        author_name=author["name"],
        added_names=[p1["name"]],
        assignee_name=assignee["name"],
        author_email=author["email"],
    )
    p1_notifs = get_user_notifications(user_email=p1["email"], user_name=p1["name"], user_id=p1["id"])
    assert any("참여 요청되었습니다" in r["title"] for r in p1_notifs)


def test_sse_slot_cap_prevents_thread_exhaustion():
    from router import _acquire_sse_slot, _release_sse_slot, _SSE_LOCK
    import router

    original_max = router._SSE_MAX_PER_USER
    router._SSE_MAX_PER_USER = 1
    try:
        user_key = "test_sse_cap_user"
        # First connection acquired
        assert _acquire_sse_slot(user_key) is True
        # Second connection from same user is rejected (saves Waitress worker thread)
        assert _acquire_sse_slot(user_key) is False

        # Release restores slot
        _release_sse_slot(user_key)
        assert _acquire_sse_slot(user_key) is True
        _release_sse_slot(user_key)
    finally:
        router._SSE_MAX_PER_USER = original_max


def test_self_notification_exclusion_sync_between_list_and_count(tmp_db):
    """
    Safeguard verification:
    Name-only self-notifications must be excluded in BOTH get_user_notifications
    and count_unread_notifications to prevent unread count badge mismatch.
    Email-addressed notifications between different accounts with duplicate names must be preserved.
    """
    from services.auth import create_user, hash_password
    from services.notification_service import (
        add_notification, get_user_notifications, count_unread_notifications
    )

    salt, hashed = hash_password("pass123")
    user = create_user(
        name="SyncUser", username="sync_user_1", org="dev",
        email="sync1@test.com", salt=salt, hash_pwd=hashed
    )

    # 1. Name-only self-notification (sender == recipient name, no email)
    add_notification(
        recipient_email="",
        recipient_name="SyncUser",
        sender_name="SyncUser",
        title="Self Task Assigned",
        content="Self assignment details",
        broadcast=False,
        realtime=False
    )

    # Both list and count must exclude this self-notification
    rows = get_user_notifications(user_email=user["email"], user_name=user["name"], user_id=user["id"])
    cnt = count_unread_notifications(user_email=user["email"], user_name=user["name"], user_id=user["id"])
    assert len(rows) == 0, "Self-notification should be excluded from list"
    assert cnt == 0, "Self-notification should be excluded from unread count"

    # 2. Legitimate notification from another user to SyncUser
    add_notification(
        recipient_email="",
        recipient_name="SyncUser",
        sender_name="OtherManager",
        title="Manager Notice",
        content="Legitimate notice",
        broadcast=False,
        realtime=False
    )

    rows2 = get_user_notifications(user_email=user["email"], user_name=user["name"], user_id=user["id"])
    cnt2 = count_unread_notifications(user_email=user["email"], user_name=user["name"], user_id=user["id"])
    assert len(rows2) == 1
    assert cnt2 == 1
    assert rows2[0]["title"] == "Manager Notice"

