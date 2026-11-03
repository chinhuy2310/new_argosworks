import re

def parse_multipart(body, boundary):
    # Parse only MIME delimiter lines. Splitting on the bare boundary token can
    # corrupt binary uploads that merely contain the same byte sequence.
    if not isinstance(body, (bytes, bytearray)) or not isinstance(boundary, str):
        raise ValueError("multipart 본문 또는 boundary 형식이 올바르지 않습니다.")
    if not boundary or len(boundary) > 200 or any(ch in boundary for ch in "\r\n"):
        raise ValueError("multipart boundary가 올바르지 않습니다.")
    if not body:
        return {}, []

    fields, files = {}, []
    boundary_bytes = ("--" + boundary).encode("utf-8")
    closing = boundary_bytes + b"--"
    if body in (closing, closing + b"\r\n"):
        return fields, files
    if not body.startswith(boundary_bytes):
        raise ValueError("multipart 본문 시작 boundary가 없습니다.")
    if not (body.endswith(closing) or body.endswith(closing + b"\r\n")):
        raise ValueError("multipart 본문이 불완전합니다. 종료 boundary가 없습니다.")

    after_opening = body[len(boundary_bytes):]
    if not after_opening.startswith(b"\r\n"):
        raise ValueError("multipart 첫 번째 part 구분자가 올바르지 않습니다.")
    payload = after_opening[2:]
    parts = payload.split(b"\r\n" + boundary_bytes)
    if not parts or parts[-1] not in (b"--", b"--\r\n"):
        raise ValueError("multipart 종료 boundary가 올바르지 않습니다.")

    for part in parts[:-1]:
        if not part:
            continue
        if b"\r\n\r\n" not in part:
            raise ValueError("multipart part 헤더가 올바르지 않습니다.")
        header_blob, content = part.split(b"\r\n\r\n", 1)
        headers = {}
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower()] = v.strip()
        disp = headers.get(b"content-disposition", b"").decode("utf-8", "replace")
        name_m = re.search(r'name="([^"]*)"', disp)
        file_m = re.search(r'filename="([^"]*)"', disp)
        if not name_m:
            raise ValueError("multipart part에 필드 이름이 없습니다.")
        field_name = name_m.group(1)
        if file_m and file_m.group(1):
            files.append({
                "field": field_name,
                "filename": file_m.group(1),
                "content_type": headers.get(b"content-type", b"application/octet-stream").decode("utf-8", "replace"),
                "data": bytes(content)
            })
        else:
            fields[field_name] = content.decode("utf-8", "replace")
    return fields, files
