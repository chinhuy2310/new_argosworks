import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import pytest
from utils.multipart import parse_multipart


def _multipart_body(boundary, close=True):
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="id"\r\n\r\n'
        "P-100\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="note.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "file contents\r\n"
    ).encode("utf-8")
    if close:
        body += f"--{boundary}--\r\n".encode("ascii")
    return body


def test_parse_multipart_accepts_complete_body():
    fields, files = parse_multipart(_multipart_body("boundary-123"), "boundary-123")
    assert fields["id"] == "P-100"
    assert len(files) == 1
    assert files[0]["filename"] == "note.txt"
    assert files[0]["data"] == b"file contents"


def test_parse_multipart_rejects_truncated_body_before_returning_files():
    with pytest.raises(ValueError, match="불완전"):
        parse_multipart(_multipart_body("boundary-123", close=False), "boundary-123")


@pytest.mark.parametrize("boundary", ["", "bad\r\nboundary", "x" * 201])
def test_parse_multipart_rejects_invalid_boundary(boundary):
    with pytest.raises(ValueError, match="boundary"):
        parse_multipart(b"", boundary)


def test_parse_multipart_preserves_boundary_token_inside_binary_content():
    boundary = "boundary-123"
    payload = b"prefix--boundary-123-middle"
    body = (
        f"--{boundary}\\r\\n"
        'Content-Disposition: form-data; name="files"; filename="binary.bin"\\r\\n'
        "Content-Type: application/octet-stream\\r\\n\\r\\n"
    ).encode("utf-8") + payload + f"\\r\\n--{boundary}--\\r\\n".encode("ascii")
    _, files = parse_multipart(body, boundary)
    assert files[0]["data"] == payload


def test_parse_multipart_accepts_empty_closed_form():
    assert parse_multipart(b"--boundary-123--\\r\\n", "boundary-123") == ({}, [])
