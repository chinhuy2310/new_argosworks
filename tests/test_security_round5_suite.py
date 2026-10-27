"""
test_security_round5_suite.py — Audit round 5 hardening.

Phạm vi (Mục 2, 3, 4 của báo cáo; Mục 1 được tạm hoãn theo yêu cầu):

* Mục 2 — ``DANGEROUS_EXTENSIONS`` phải bao phủ cả script (.py/.pyw) và payload
  Java/.NET (.jar/.jsp/.war/.asp/.aspx/.shtml...) chứ không chỉ .html/.js/.exe.
* Mục 3 — Mọi đường dẫn file đính kèm phải đi qua ``safe_join()``: product
  download / upload / delete không được phép thoát khỏi thư mục của nó
  (``os.path.join`` + ``..`` trước đây cho phép đọc/ghi/xoá ngoài thư mục).
* Mục 4 — Webhook ra ngoài phải chặn scheme lạ (``file://``, ``ftp://``) và
  IP nội bộ/loopback/link-local, kể cả khi bị redirect (SSRF).
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from unittest.mock import MagicMock, Mock, patch

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


MANAGER = {
    "id": 995110, "user_id": 995110, "username": "r5_manager", "name": "R5 Manager",
    "role": "manager", "org": "dev", "dept_id": "dev", "is_admin": 0,
    "email": "r5_manager@test.local",
}
ADMIN = {
    "id": 995111, "user_id": 995111, "username": "r5_admin", "name": "R5 Admin",
    "role": "admin", "org": "mgmt", "dept_id": "mgmt", "is_admin": 1,
    "email": "r5_admin@test.local",
}


class _Handler:
    """Minimal handler stub capturing the JSON response / streamed attachment."""

    def __init__(self, session=None):
        self.session = session
        self.status = None
        self.body = None
        self.sent_file = None
        self.headers = {}
        self.cfg = {"jira": {"enabled": False, "api_token": ""}, "ai": {}, "voyage": {}}

    def _get_session_or_401(self):
        if not self.session:
            self._send_json(401, {"ok": False, "error": "인증이 필요합니다."})
            return None
        return self.session

    def _get_session_optional(self):
        return self.session

    def _send_json(self, status, payload, extra_headers=None):
        self.status = status
        self.body = payload

    def _send_attachment(self, path, download_name):
        self.sent_file = path
        self.status = 200


def _build_multipart(boundary, fields, file_parts):
    """Builds a multipart/form-data body: {name: value} fields + [(field, filename, bytes)]."""
    chunks = []
    for key, value in fields.items():
        chunks.append(
            ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, key, value)).encode()
        )
    for field, filename, content in file_parts:
        chunks.append(
            ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
             "Content-Type: text/plain\r\n\r\n" % (boundary, field, filename)).encode()
        )
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(("--%s--\r\n" % boundary).encode())
    return b"".join(chunks), "multipart/form-data; boundary=%s" % boundary


def _seed_product(tmp_db, pid, attachments=()):
    """Insert a product row + product_attachments rows (names are stored verbatim)."""
    now = "2026-01-01T00:00:00"
    tmp_db.execute(
        """INSERT INTO products
             (id, model, display_name, family, lifecycle, category, summary, memo,
              specs, procurement, price, currency, revision, created_at, updated_at, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pid, "R5-MODEL", "R5 Product", "", "판매 중", "일반", "", "", "{}", None,
         1000, "KRW", 1, now, now, "internal"),
    )
    for name, size in attachments:
        tmp_db.execute(
            "INSERT INTO product_attachments (product_id, filename, file_size, uploaded_at) VALUES (?, ?, ?, ?)",
            (pid, name, size, now),
        )


@pytest.fixture
def attach_dirs(tmp_path, monkeypatch):
    """Point PRODUCT_ATTACH_DIR / ATTACH_DIR at a throw-away directory."""
    import router as router_module
    import handlers.product_handlers as product_handlers

    product_dir = tmp_path / "products"
    product_dir.mkdir()
    attach_dir = tmp_path / "attachments"
    attach_dir.mkdir()
    monkeypatch.setattr(router_module, "PRODUCT_ATTACH_DIR", str(product_dir), raising=False)
    monkeypatch.setattr(router_module, "ATTACH_DIR", str(attach_dir), raising=False)
    monkeypatch.setattr(product_handlers, "PRODUCT_ATTACH_DIR", str(product_dir), raising=False)
    monkeypatch.setattr("services.license_manager.is_system_read_only", lambda: False)
    return {"products": product_dir, "attachments": attach_dir, "tmp": tmp_path}



# ===========================================================================
# Mục 2 — dangerous extensions
# ===========================================================================
class TestDangerousExtensions:
    @pytest.mark.parametrize("name", [
        "script.py", "window.pyw", "app.jar", "page.jsp", "page.jspx",
        "app.war", "classic.asp", "modern.aspx", "server.shtml",
        "payload.class", "drop.msi", "shortcut.lnk", "mod.wasm",
        "evil.html", "evil.svg", "evil.js", "evil.php", "evil.ps1",
    ])
    def test_dangerous_extensions_become_bin(self, name):
        from utils.file_ops import sanitize_filename
        out = sanitize_filename(name)
        assert out.endswith(".bin"), f"{name} -> {out}"

    @pytest.mark.parametrize("name", ["report.pdf", "photo.jpg", "data.xlsx", "notes.txt", "archive.zip"])
    def test_safe_extensions_preserved(self, name):
        from utils.file_ops import sanitize_filename
        assert sanitize_filename(name) == name

    def test_uppercase_extension_blocked(self):
        from utils.file_ops import sanitize_filename
        assert sanitize_filename("TOOL.PY").endswith(".bin")
        assert sanitize_filename("APP.JAR").endswith(".bin")


# ===========================================================================
# Mục 3 — safe_join + path traversal
# ===========================================================================
class TestSafeJoin:
    def test_normal_nested_path(self, tmp_path):
        from utils.file_ops import safe_join
        base = tmp_path / "attach"
        base.mkdir()
        assert safe_join(str(base), "123", "a.pdf") == os.path.realpath(str(base / "123" / "a.pdf"))

    def test_parent_traversal_rejected(self, tmp_path):
        from utils.file_ops import safe_join
        base = tmp_path / "attach"
        base.mkdir()
        assert safe_join(str(base), "..", "secret.txt") is None
        assert safe_join(str(base), "123", "../..", "secret.txt") is None

    def test_sibling_prefix_is_not_a_child(self, tmp_path):
        """'…/attach_evil' must not be accepted as '…/attach' (commonpath, not startswith)."""
        from utils.file_ops import safe_join
        base = tmp_path / "attach"
        base.mkdir()
        (tmp_path / "attach_evil").mkdir()
        assert safe_join(str(base), "..", "attach_evil", "x.txt") is None

    def test_absolute_component_rejected(self, tmp_path):
        from utils.file_ops import safe_join
        base = tmp_path / "attach"
        base.mkdir()
        assert safe_join(str(base), str(tmp_path / "outside.txt")) is None

    def test_windows_separators_rejected(self, tmp_path):
        from utils.file_ops import safe_join
        base = tmp_path / "attach"
        base.mkdir()
        assert safe_join(str(base), "..", "..", "boot.ini") is None

    def test_empty_base_rejected(self):
        from utils.file_ops import safe_join
        assert safe_join("", "a.txt") is None


# ===========================================================================
# Mục 3 — PIM attachment routes (download / upload / delete)
# ===========================================================================
class TestPimAttachmentTraversal:
    def test_download_blocks_traversal_attachment_name(self, tmp_db, attach_dirs):
        import router as router_module

        base = attach_dirs["products"]
        secret = base / "r5_escape.txt"
        secret.write_text("TOP-SECRET", encoding="utf-8")
        pid = "P-r5-dl"
        (base / pid).mkdir()
        _seed_product(tmp_db, pid, [("../r5_escape.txt", len("TOP-SECRET"))])

        handler = _Handler(MANAGER)
        router_module.handle_get_products_attachment(
            handler,
            urllib.parse.urlsplit("/api/products/attachment?id=%s&file=../r5_escape.txt" % pid),
            "127.0.0.1",
        )
        assert handler.status == 404, handler.body
        assert handler.sent_file is None

    def test_download_serves_file_inside_product_dir(self, tmp_db, attach_dirs):
        import router as router_module

        base = attach_dirs["products"]
        pid = "P-r5-ok"
        product_dir = base / pid
        product_dir.mkdir()
        (product_dir / "ok.txt").write_text("hello", encoding="utf-8")
        _seed_product(tmp_db, pid, [("ok.txt", 5)])

        handler = _Handler(MANAGER)
        router_module.handle_get_products_attachment(
            handler,
            urllib.parse.urlsplit("/api/products/attachment?id=%s&file=ok.txt" % pid),
            "127.0.0.1",
        )
        assert handler.status == 200, handler.body
        assert handler.sent_file.endswith("ok.txt")

    def test_delete_blocks_traversal_and_keeps_outside_file(self, tmp_db, attach_dirs):
        import handlers.product_handlers as product_handlers

        base = attach_dirs["products"]
        secret = base / "r5_escape_del.txt"
        secret.write_text("KEEP", encoding="utf-8")
        pid = "P-r5-del"
        (base / pid).mkdir()
        _seed_product(tmp_db, pid, [("../r5_escape_del.txt", 4)])

        handler = _Handler(MANAGER)
        body = json.dumps({"id": pid, "name": "../r5_escape_del.txt"}).encode("utf-8")
        product_handlers.handle_product_attachment_delete(handler, body, "127.0.0.1")

        assert handler.status == 404, handler.body
        assert secret.exists(), "file outside the product directory must not be deleted"

    def test_delete_removes_file_inside_product_dir(self, tmp_db, attach_dirs):
        import handlers.product_handlers as product_handlers

        base = attach_dirs["products"]
        pid = "P-r5-del-ok"
        product_dir = base / pid
        product_dir.mkdir()
        target = product_dir / "gone.txt"
        target.write_text("bye", encoding="utf-8")
        _seed_product(tmp_db, pid, [("gone.txt", 3)])

        handler = _Handler(MANAGER)
        body = json.dumps({"id": pid, "name": "gone.txt"}).encode("utf-8")
        product_handlers.handle_product_attachment_delete(handler, body, "127.0.0.1")

        assert handler.status == 200, handler.body
        assert not target.exists()

    def test_upload_rejects_traversal_product_id(self, tmp_db, attach_dirs):
        import handlers.product_handlers as product_handlers

        pid = "../r5_evil"
        _seed_product(tmp_db, pid)
        body, ctype = _build_multipart("r5boundary", {"id": pid}, [("file", "note.txt", b"hacked")])

        handler = _Handler(MANAGER)
        handler.headers["Content-Type"] = ctype
        product_handlers.handle_product_attachment_upload(handler, body, "127.0.0.1")

        assert handler.status == 400, handler.body
        assert not (attach_dirs["tmp"] / "r5_evil").exists(), "must not create a directory outside the product root"

    def test_upload_writes_inside_product_dir(self, tmp_db, attach_dirs):
        import handlers.product_handlers as product_handlers

        base = attach_dirs["products"]
        pid = "P-r5-up"
        (base / pid).mkdir()
        _seed_product(tmp_db, pid)
        body, ctype = _build_multipart("r5boundary", {"id": pid}, [("file", "note.txt", b"hello world")])

        handler = _Handler(MANAGER)
        handler.headers["Content-Type"] = ctype
        product_handlers.handle_product_attachment_upload(handler, body, "127.0.0.1")

        assert handler.status == 200, handler.body
        assert (base / pid / "note.txt").is_file()


# ===========================================================================
# Mục 4 — outgoing webhook SSRF
# ===========================================================================
class TestWebhookSsrf:
    @pytest.mark.parametrize("url", [
        "file:///C:/Windows/win.ini",
        "file:///etc/passwd",
        "ftp://example.com/hook",
        "gopher://127.0.0.1:6379/_INFO",
        "javascript:alert(1)",
    ])
    def test_non_http_schemes_are_rejected(self, url):
        from services import webhook_dispatcher as wd

        opener = MagicMock()
        with patch.object(wd, "_OPENER", opener):
            result = wd._send_http_post(url, {"event": "test"})

        assert result == "invalid_scheme", result
        opener.open.assert_not_called()

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:8000/hook",
        "https://127.0.0.1/hook",
        "http://localhost:9000/hook",
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/latest/meta-data/iam/",
        "http://10.1.2.3/hook",
        "http://192.168.1.5/hook",
    ])
    def test_internal_targets_are_blocked(self, url):
        from services import webhook_dispatcher as wd

        opener = MagicMock()
        with patch.object(wd, "_OPENER", opener):
            result = wd._send_http_post(url, {"event": "test"})

        assert result == "blocked_host", result
        opener.open.assert_not_called()

    def test_empty_url_is_rejected(self):
        from services.webhook_dispatcher import _send_http_post
        assert _send_http_post("", {}) == "invalid_url"
        assert _send_http_post(None, {}) == "invalid_url"

    def test_public_https_target_is_sent(self):
        from services import webhook_dispatcher as wd

        opener = MagicMock()
        with patch.object(wd, "_OPENER", opener), \
             patch.object(wd, "validate_external_url", lambda *a, **k: True):
            result = wd._send_http_post("https://hooks.slack.com/services/T/B/X", {"event": "test"})

        assert result is None, result
        opener.open.assert_called_once()
        sent_request = opener.open.call_args[0][0]
        assert sent_request.full_url == "https://hooks.slack.com/services/T/B/X"
        assert sent_request.get_method() == "POST"

    def test_redirect_to_internal_ip_is_refused(self):
        from services.webhook_dispatcher import _ValidatedRedirectHandler

        handler = _ValidatedRedirectHandler()
        request = urllib.request.Request("https://hooks.slack.com/services/T/B/X")
        assert handler.redirect_request(
            request, None, 302, "Found", {},
            "http://169.254.169.254/latest/meta-data/",
        ) is None

    def test_redirect_to_other_file_scheme_is_refused(self):
        from services.webhook_dispatcher import _ValidatedRedirectHandler

        handler = _ValidatedRedirectHandler()
        request = urllib.request.Request("https://hooks.slack.com/services/T/B/X")
        assert handler.redirect_request(request, None, 301, "Moved", {}, "file:///C:/Windows/win.ini") is None

    def test_validate_webhook_target_accepts_public_https(self):
        from services import webhook_dispatcher as wd
        with patch.object(wd, "validate_external_url", lambda *a, **k: True):
            assert wd.validate_webhook_target("https://hooks.slack.com/services/x") == (True, "")


# ===========================================================================
# Mục 4 — /api/settings must refuse unsafe webhook URLs before writing .env
# ===========================================================================
class TestSettingsWebhookValidation:
    @pytest.mark.parametrize("key,url", [
        ("SLACK_WEBHOOK_URL", "http://127.0.0.1:9999/hook"),
        ("TEAMS_WEBHOOK_URL", "file:///C:/Windows/win.ini"),
        ("GENERIC_WEBHOOK_URL", "http://169.254.169.254/latest/meta-data/"),
        ("GENERIC_WEBHOOK_URL", "http://example.com/plain-http"),
    ])
    def test_admin_save_rejects_unsafe_webhook_url(self, key, url):
        import handlers.settings_handler as settings_handler

        writer = Mock()
        handler = _Handler(ADMIN)
        with patch.object(settings_handler, "_write_env_updates", writer):
            settings_handler.handle_post_settings(
                handler,
                json.dumps({"settings": {key: url}}).encode("utf-8"),
                "127.0.0.1",
            )

        assert handler.status == 400, handler.body
        writer.assert_not_called()
        assert key in (handler.body or {}).get("error", "")

    def test_non_admin_cannot_save_webhook_settings(self):
        import handlers.settings_handler as settings_handler

        writer = Mock()
        handler = _Handler(MANAGER)
        with patch.object(settings_handler, "_write_env_updates", writer):
            settings_handler.handle_post_settings(
                handler,
                json.dumps({"settings": {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/x"}}).encode("utf-8"),
                "127.0.0.1",
            )

        assert handler.status == 403, handler.body
        writer.assert_not_called()
