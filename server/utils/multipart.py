import re

def parse_multipart(body, boundary):
    # 주의: 파일 내용의 끝부분이 \r 또는 \n으로 끝날 수 있으므로, 여기서는 절대
    # bytes.strip(b"\r\n") 같은 "양끝의 해당 문자 전부 제거"를 쓰면 안 된다 —
    # 실제 파일 내용의 마지막 개행 문자까지 함께 지워지는 버그가 생긴다.
    # 반드시 MIME 구분자가 만드는 정확히 2바이트(앞 \r\n, 뒤 \r\n)만 슬라이싱으로 제거한다.
    if not isinstance(body, (bytes, bytearray)) or not isinstance(boundary, str):
        raise ValueError("multipart 본문 또는 boundary 형식이 올바르지 않습니다.")
    if not boundary or len(boundary) > 200 or any(ch in boundary for ch in "\r\n"):
        raise ValueError("multipart boundary가 올바르지 않습니다.")

    if not body:
        return {}, []

    fields, files = {}, []
    boundary_bytes = ("--" + boundary).encode("utf-8")
    # A truncated HTTP body can still contain a syntactically plausible first
    # part. Require the final MIME closing delimiter before accepting any data.
    if not body.startswith(boundary_bytes):
        raise ValueError("multipart 본문 시작 boundary가 없습니다.")
    if not (
        body.endswith(boundary_bytes + b"--")
        or body.endswith(boundary_bytes + b"--\r\n")
    ):
        raise ValueError("multipart 본문이 불완전합니다. 종료 boundary가 없습니다.")

    for raw_part in body.split(boundary_bytes):
        part = raw_part[2:] if raw_part.startswith(b"\r\n") else raw_part
        if not part or part in (b"--", b"--\r\n", b"\r\n"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        content = content[:-2] if content.endswith(b"\r\n") else content
        headers = {}
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower()] = v.strip()
        disp = headers.get(b"content-disposition", b"").decode("utf-8", "replace")
        name_m = re.search(r'name="([^"]*)"', disp)
        file_m = re.search(r'filename="([^"]*)"', disp)
        if not name_m:
            continue
        field_name = name_m.group(1)
        if file_m and file_m.group(1):
            files.append({
                "field": field_name,
                "filename": file_m.group(1),
                "content_type": headers.get(b"content-type", b"application/octet-stream").decode("utf-8", "replace"),
                "data": content
            })
        else:
            fields[field_name] = content.decode("utf-8", "replace")
    return fields, files
