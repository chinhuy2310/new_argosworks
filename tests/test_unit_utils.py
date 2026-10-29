"""
test_unit_utils.py — Unit Tests cho tất cả utility modules
Kiểm tra: text.py, file_ops.py, multipart.py, crypto.py
Bao gồm edge cases: dữ liệu rỗng, sai định dạng, ký tự đặc biệt, Unicode
"""
import os
import sys
import json
import tempfile
import shutil
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("ARGOS_MASTER_KEY", "test-master-key-for-unit-tests-2026")


# ============================================================================
# 1. text.py — Hàm xử lý văn bản, parse timestamp, sanitize label
# ============================================================================
class TestParseIsoTimestamp:
    """parse_iso_timestamp: chuyển đổi ISO timestamp sang KST."""

    def test_utc_z_suffix(self):
        from utils.text import parse_iso_timestamp
        result = parse_iso_timestamp("2026-03-15T10:30:00Z")
        assert result == "2026-03-15 19:30:00"  # UTC +9 = KST

    def test_utc_offset_format(self):
        from utils.text import parse_iso_timestamp
        result = parse_iso_timestamp("2026-03-15T10:30:00+00:00")
        assert result == "2026-03-15 19:30:00"

    def test_kst_timezone(self):
        from utils.text import parse_iso_timestamp
        result = parse_iso_timestamp("2026-03-15T10:30:00+09:00")
        assert result == "2026-03-15 10:30:00"

    def test_no_timezone(self):
        from utils.text import parse_iso_timestamp
        result = parse_iso_timestamp("2026-03-15T10:30:00")
        assert result == "2026-03-15 10:30:00"

    def test_empty_string(self):
        from utils.text import parse_iso_timestamp
        assert parse_iso_timestamp("") == ""

    def test_none_value(self):
        from utils.text import parse_iso_timestamp
        assert parse_iso_timestamp(None) == ""

    def test_invalid_format_graceful(self):
        from utils.text import parse_iso_timestamp
        result = parse_iso_timestamp("not-a-date")
        assert isinstance(result, str)

    def test_milliseconds_stripped(self):
        from utils.text import parse_iso_timestamp
        result = parse_iso_timestamp("2026-03-15T10:30:00.123456")
        assert "." not in result
        assert len(result) <= 19


class TestSanitizeLabel:
    """sanitize_label: xóa ký tự nguy hiểm, giới hạn 60 ký tự."""

    def test_normal_text(self):
        from utils.text import sanitize_label
        assert sanitize_label("서버개발") == "서버개발"

    def test_spaces_replaced(self):
        from utils.text import sanitize_label
        result = sanitize_label("서버 개발 팀")
        assert " " not in result
        assert "_" in result

    def test_commas_replaced(self):
        from utils.text import sanitize_label
        result = sanitize_label("A,B,C")
        assert "," not in result

    def test_special_chars_removed(self):
        from utils.text import sanitize_label
        result = sanitize_label("test<script>alert(1)</script>")
        assert "<" not in result
        assert ">" not in result

    def test_empty_returns_default(self):
        from utils.text import sanitize_label
        assert sanitize_label("") == "미지정"
        assert sanitize_label(None) == "미지정"

    def test_max_length_60(self):
        from utils.text import sanitize_label
        result = sanitize_label("A" * 100)
        assert len(result) <= 60


class TestAssigneeBaseName:
    """assignee_base_name: tách tên cơ bản (bỏ chức danh)."""

    def test_with_title_suffix(self):
        from utils.text import assignee_base_name
        assert assignee_base_name("김철수팀장") == "김철수"
        assert assignee_base_name("박영희대리") == "박영희"

    def test_no_suffix(self):
        from utils.text import assignee_base_name
        assert assignee_base_name("이민호") == "이민호"

    def test_empty_and_none(self):
        from utils.text import assignee_base_name
        assert assignee_base_name("") == ""
        assert assignee_base_name(None) == ""

    def test_only_suffix(self):
        from utils.text import assignee_base_name
        # When name equals suffix exactly, it should return as-is
        result = assignee_base_name("팀장")
        assert result == "팀장"


class TestGuessCategory:
    """guess_category: tự phân loại dựa trên keywords."""

    def test_returns_category_string(self):
        from utils.text import guess_category
        result = guess_category("일반 업무")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_input(self):
        from utils.text import guess_category
        result = guess_category("")
        assert result == "기타업무"

    def test_none_input(self):
        from utils.text import guess_category
        result = guess_category(None)
        assert result == "기타업무"


class TestAdfToText:
    """_adf_to_text: trích xuất văn bản từ Jira ADF (JSON)."""

    def test_simple_adf(self):
        from utils.text import _adf_to_text
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "World"}
                    ]
                }
            ]
        }
        result = _adf_to_text(adf)
        assert "Hello" in result and "World" in result

    def test_empty_adf(self):
        from utils.text import _adf_to_text
        assert _adf_to_text({}) == ""

    def test_none_adf(self):
        from utils.text import _adf_to_text
        assert _adf_to_text(None) == ""

    def test_nested_content(self):
        from utils.text import _adf_to_text
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "panel",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "nested"}]
                        }
                    ]
                }
            ]
        }
        assert "nested" in _adf_to_text(adf)

    def test_list_input(self):
        from utils.text import _adf_to_text
        adf_list = [{"type": "text", "text": "item1"}, {"type": "text", "text": "item2"}]
        result = _adf_to_text(adf_list)
        assert "item1" in result
        assert "item2" in result


# ============================================================================
# 2. file_ops.py — Xử lý file, sanitize filename, atomic write
# ============================================================================
class TestSanitizeFilename:
    """sanitize_filename: ngăn directory traversal và XSS/Code execution."""

    def test_normal_filename(self):
        from utils.file_ops import sanitize_filename
        assert sanitize_filename("report.pdf") == "report.pdf"

    def test_directory_traversal_blocked(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_windows_path_stripped(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("C:\\Windows\\system32\\cmd.exe")
        assert "C:" not in result
        assert "Windows" not in result

    def test_html_extension_blocked(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("xss.html")
        assert not result.endswith(".html")
        assert result.endswith(".bin")

    def test_js_extension_blocked(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("evil.js")
        assert not result.endswith(".js")
        assert result.endswith(".bin")

    def test_svg_extension_blocked(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("malicious.svg")
        assert not result.endswith(".svg")

    def test_exe_extension_blocked(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("virus.exe")
        assert not result.endswith(".exe")

    def test_safe_extensions_allowed(self):
        from utils.file_ops import sanitize_filename
        assert sanitize_filename("photo.jpg").endswith(".jpg")
        assert sanitize_filename("doc.pdf").endswith(".pdf")
        assert sanitize_filename("data.xlsx").endswith(".xlsx")
        assert sanitize_filename("image.png").endswith(".png")

    def test_empty_filename(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("")
        assert result in ("file.bin", "file")  # Depends on default extension handling

    def test_none_filename(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename(None)
        assert result in ("file.bin", "file")

    def test_special_chars_removed(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename('file"name<>|test.pdf')
        assert '"' not in result
        assert '<' not in result
        assert '>' not in result
        assert '|' not in result

    def test_null_bytes_removed(self):
        from utils.file_ops import sanitize_filename
        result = sanitize_filename("file\x00name.pdf")
        assert "\x00" not in result


class TestUniqueAttachmentName:
    """unique_attachment_name: không ghi đè file trùng tên."""

    def test_no_conflict(self):
        from utils.file_ops import unique_attachment_name
        with tempfile.TemporaryDirectory() as d:
            assert unique_attachment_name(d, "test.pdf") == "test.pdf"

    def test_conflict_auto_increment(self):
        from utils.file_ops import unique_attachment_name
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "test.pdf"), "w").close()
            assert unique_attachment_name(d, "test.pdf") == "test(2).pdf"

    def test_multiple_conflicts(self):
        from utils.file_ops import unique_attachment_name
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "test.pdf"), "w").close()
            open(os.path.join(d, "test(2).pdf"), "w").close()
            assert unique_attachment_name(d, "test.pdf") == "test(3).pdf"


class TestAtomicWriteJson:
    """atomic_write_json: ghi JSON an toàn (tmp + replace)."""

    def test_basic_write(self):
        from utils.file_ops import atomic_write_json
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            data = {"key": "value", "num": 42}
            atomic_write_json(path, data)
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded == data

    def test_unicode_content(self):
        from utils.file_ops import atomic_write_json
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            data = {"이름": "홍길동", "부서": "개발팀"}
            atomic_write_json(path, data)
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["이름"] == "홍길동"

    def test_overwrite_existing(self):
        from utils.file_ops import atomic_write_json
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            atomic_write_json(path, {"v": 1})
            atomic_write_json(path, {"v": 2})
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["v"] == 2


# ============================================================================
# 3. multipart.py — Phân tích multipart/form-data
# ============================================================================
class TestParseMultipart:
    """parse_multipart: phân tích multipart form data."""

    def _build_multipart(self, boundary, parts):
        """Helper: xây dựng body multipart hợp lệ."""
        body = b""
        for part in parts:
            body += f"--{boundary}\r\n".encode()
            if "filename" in part:
                body += f'Content-Disposition: form-data; name="{part["name"]}"; filename="{part["filename"]}"\r\n'.encode()
                body += f'Content-Type: {part.get("content_type", "application/octet-stream")}\r\n'.encode()
            else:
                body += f'Content-Disposition: form-data; name="{part["name"]}"\r\n'.encode()
            body += b"\r\n"
            if isinstance(part["data"], bytes):
                body += part["data"]
            else:
                body += part["data"].encode("utf-8")
            body += b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        return body

    def test_text_fields(self):
        from utils.multipart import parse_multipart
        body = self._build_multipart("boundary123", [
            {"name": "title", "data": "Test Title"},
            {"name": "category", "data": "기능개발"}
        ])
        fields, files = parse_multipart(body, "boundary123")
        assert fields["title"] == "Test Title"
        assert fields["category"] == "기능개발"
        assert len(files) == 0

    def test_file_upload(self):
        from utils.multipart import parse_multipart
        file_content = b"PDF file content here"
        body = self._build_multipart("bnd", [
            {"name": "title", "data": "Test"},
            {"name": "file", "data": file_content, "filename": "report.pdf",
             "content_type": "application/pdf"}
        ])
        fields, files = parse_multipart(body, "bnd")
        assert fields["title"] == "Test"
        assert len(files) == 1
        assert files[0]["filename"] == "report.pdf"
        assert files[0]["data"] == file_content

    def test_multiple_files(self):
        from utils.multipart import parse_multipart
        body = self._build_multipart("bnd", [
            {"name": "file1", "data": b"content1", "filename": "a.pdf"},
            {"name": "file2", "data": b"content2", "filename": "b.png"}
        ])
        _, files = parse_multipart(body, "bnd")
        assert len(files) == 2

    def test_empty_body(self):
        from utils.multipart import parse_multipart
        fields, files = parse_multipart(b"", "boundary")
        assert fields == {}
        assert files == []

    def test_unicode_filename(self):
        from utils.multipart import parse_multipart
        body = self._build_multipart("bnd", [
            {"name": "file", "data": b"data", "filename": "보고서_2026.xlsx"}
        ])
        _, files = parse_multipart(body, "bnd")
        assert len(files) == 1
        assert files[0]["filename"] == "보고서_2026.xlsx"

    def test_binary_file_content_preserved(self):
        from utils.multipart import parse_multipart
        binary_data = bytes(range(256))
        body = self._build_multipart("bnd", [
            {"name": "file", "data": binary_data, "filename": "binary.dat"}
        ])
        _, files = parse_multipart(body, "bnd")
        assert files[0]["data"] == binary_data


# ============================================================================
# 4. crypto.py — AES-256-CBC + HMAC-SHA256 Encryption
# ============================================================================
class TestCryptoEncryption:
    """encrypt_secret / decrypt_secret: mã hóa / giải mã bí mật."""

    def test_roundtrip(self):
        from utils.crypto import encrypt_secret, decrypt_secret
        plain = "super-secret-jira-api-token-2026!@#$%^"
        enc = encrypt_secret(plain)
        dec = decrypt_secret(enc)
        assert dec == plain

    def test_prefix_format(self):
        from utils.crypto import encrypt_secret, is_encrypted
        enc = encrypt_secret("test")
        assert is_encrypted(enc)
        assert enc.startswith("enc:v1:")

    def test_empty_passthrough(self):
        from utils.crypto import encrypt_secret, decrypt_secret
        assert encrypt_secret("") == ""
        assert encrypt_secret(None) == ""
        assert decrypt_secret("") == ""
        assert decrypt_secret(None) == ""

    def test_plain_text_passthrough(self):
        from utils.crypto import decrypt_secret
        assert decrypt_secret("plain_text") == "plain_text"

    def test_already_encrypted_idempotent(self):
        from utils.crypto import encrypt_secret
        enc1 = encrypt_secret("test")
        enc2 = encrypt_secret(enc1)
        assert enc1 == enc2  # Should not double-encrypt

    def test_tamper_detection(self):
        from utils.crypto import encrypt_secret, decrypt_secret
        enc = encrypt_secret("sensitive-value")
        tampered = enc[:-4] + "AAAA"
        dec = decrypt_secret(tampered)
        assert dec == ""  # HMAC fails

    def test_different_values_different_ciphertext(self):
        from utils.crypto import encrypt_secret
        enc1 = encrypt_secret("value1")
        enc2 = encrypt_secret("value2")
        assert enc1 != enc2

    def test_same_value_different_ciphertext(self):
        """Random IV ensures different ciphertext each time."""
        from utils.crypto import encrypt_secret
        enc1 = encrypt_secret("same-value")
        enc2 = encrypt_secret("same-value")
        assert enc1 != enc2  # Different IVs

    def test_unicode_roundtrip(self):
        from utils.crypto import encrypt_secret, decrypt_secret
        plain = "한글 비밀번호 🔐 テスト"
        enc = encrypt_secret(plain)
        dec = decrypt_secret(enc)
        assert dec == plain

    def test_long_value_roundtrip(self):
        from utils.crypto import encrypt_secret, decrypt_secret
        plain = "A" * 10000
        enc = encrypt_secret(plain)
        dec = decrypt_secret(enc)
        assert dec == plain

    def test_is_encrypted_checks(self):
        from utils.crypto import is_encrypted
        assert is_encrypted("enc:v1:AAAA") is True
        assert is_encrypted("plain-text") is False
        assert is_encrypted("") is False
        assert is_encrypted(None) is False
        assert is_encrypted(123) is False


# ============================================================================
# 5. SSRF Validator — validate_external_url
# ============================================================================
class TestSSRFValidator:
    """validate_external_url: chặn SSRF attacks."""

    def test_valid_https_url(self):
        from utils.ssrf import validate_external_url
        from unittest.mock import patch
        with patch("utils.ssrf.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            result = validate_external_url("https://www.google.com", require_https=True)
            assert result is True

    def test_reject_http_without_allow(self):
        from utils.ssrf import validate_external_url
        with pytest.raises(ValueError, match="HTTPS"):
            validate_external_url("http://example.com", require_https=True)

    def test_reject_empty_url(self):
        from utils.ssrf import validate_external_url
        with pytest.raises(ValueError):
            validate_external_url("")
        with pytest.raises(ValueError):
            validate_external_url(None)

    def test_reject_ftp_scheme(self):
        from utils.ssrf import validate_external_url
        with pytest.raises(ValueError, match="프로토콜"):
            validate_external_url("ftp://evil.com", allow_private=True)

    def test_reject_cloud_metadata(self):
        """Cloud metadata IP 169.254.169.254 phải bị chặn."""
        from utils.ssrf import validate_external_url
        with pytest.raises(ValueError, match="Link-local|메타데이터"):
            validate_external_url("http://169.254.169.254/latest/meta-data/", allow_private=True)

    def test_reject_private_ip(self):
        from utils.ssrf import validate_external_url
        with pytest.raises(ValueError):
            validate_external_url("https://192.168.1.1/admin", require_https=True)

    def test_allow_private_when_flagged(self):
        from utils.ssrf import validate_external_url
        # localhost with allow_private=True should pass
        result = validate_external_url("http://127.0.0.1:11434/api/generate", allow_private=True)
        assert result is True

    def test_cgnat_blocked_by_default_and_allowed_when_flagged(self):
        from utils.ssrf import validate_external_url
        with pytest.raises(ValueError, match="사설망|비공개"):
            validate_external_url("http://100.64.0.1/test", allow_private=False, require_https=False)
        assert validate_external_url("http://100.64.0.1/test", allow_private=True, require_https=False) is True

    def test_dns_rebinding_connection_uses_first_validated_ip(self):
        from utils.ssrf import safe_urlopen
        from unittest.mock import patch, MagicMock

        # Simulate DNS Rebinding: 1st resolve returns public IP, 2nd resolve returns loopback/private IP
        dns_calls = [
            [(2, 1, 6, "", ("93.184.216.34", 80))],
            [(2, 1, 6, "", ("127.0.0.1", 80))]
        ]

        def mock_getaddrinfo(*args, **kwargs):
            if dns_calls:
                return dns_calls.pop(0)
            return [(2, 1, 6, "", ("127.0.0.1", 80))]

        connected_addresses = []

        def mock_create_connection(address, timeout=None, source_address=None):
            connected_addresses.append(address)
            mock_sock = MagicMock()
            mock_sock.makefile.return_value = MagicMock(
                readline=MagicMock(side_effect=[b"HTTP/1.1 200 OK\r\n", b"Content-Length: 2\r\n", b"\r\n"]),
                read=MagicMock(return_value=b"OK")
            )
            return mock_sock

        with patch("utils.ssrf.socket.getaddrinfo", side_effect=mock_getaddrinfo), \
             patch("utils.ssrf.socket.create_connection", side_effect=mock_create_connection):
            resp = safe_urlopen("http://rebind.attacker.local/status", allow_private=False, require_https=False)
            assert resp.status == 200

        # The connection MUST connect to 93.184.216.34 (the validated IP from call 1), NOT 127.0.0.1!
        assert len(connected_addresses) == 1
        assert connected_addresses[0][0] == "93.184.216.34", f"Expected validated IP 93.184.216.34 but connected to {connected_addresses[0]}"

    def test_redirect_to_private_ip_is_blocked(self):
        from utils.ssrf import _SafeRedirectHandler
        import urllib.request

        handler = _SafeRedirectHandler(allow_private=False, require_https=False)
        req = urllib.request.Request("http://attacker.com/orig")
        # Redirecting to 192.168.1.1 must raise ValueError
        with pytest.raises(ValueError, match="사설망|비공개"):
            handler.redirect_request(req, None, 302, "Found", {}, "http://192.168.1.1/secret")
