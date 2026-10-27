import os
import re
import json

DANGEROUS_EXTENSIONS = {
    ".html", ".htm", ".xhtml", ".svg", ".js", ".mjs", ".xml",
    ".php", ".phtml", ".exe", ".sh", ".bat", ".cmd", ".ps1",
    ".vbs", ".scr", ".dll", ".so", ".dylib", ".cgi", ".pl",
    # Server-side scripts and Java/.NET payloads. The HTTP layer always serves
    # attachments as downloads with CSP sandbox, so these cannot be rendered or
    # executed by the web server itself — but a stored .py/.jar inside the data
    # directory must never be importable/executable by internal tooling either.
    ".py", ".pyw", ".pyc", ".jar", ".class", ".jsp", ".jspx", ".war",
    ".asp", ".aspx", ".ascx", ".ashx", ".asmx", ".shtml", ".htaccess",
    ".msi", ".lnk", ".reg", ".wasm",
}

def atomic_write_json(filepath, data):
    """Write JSON data atomically using temp file + os.replace"""
    tmp = filepath + f'.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, filepath)

def safe_join(base_dir, *parts):
    """
    Join `parts` onto `base_dir` and guarantee the result stays inside it.

    Returns the real path, or None when the joined path escapes the base directory
    (``..`` traversal, absolute component, symlink pointing outside, different
    drive). Callers must treat None as "not found" instead of touching the disk.

    Every user-influenced path segment (record id, product id, attachment name)
    must go through this helper — ``os.path.join`` alone silently allows ``..``.
    """
    if not base_dir:
        return None
    try:
        base = os.path.realpath(base_dir)
        target = os.path.realpath(os.path.join(base, *[str(p) for p in parts]))
        # commonpath (not startswith) so ".../attach_evil" cannot pass as
        # ".../attach"; it also normalises the separator difference on Windows.
        if os.path.commonpath([target, base]) != base:
            return None
        return target
    except (ValueError, TypeError, OSError):
        return None

def sanitize_filename(name):
    """Sanitize filename to prevent directory traversal and stored XSS/code execution.
    Dangerous extensions (.html, .svg, .js, etc.) are converted to .bin.
    """
    name = os.path.basename(name or "file")
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip()
    if not name:
        name = "file.bin"
    base, ext = os.path.splitext(name)
    if ext.lower() in DANGEROUS_EXTENSIONS:
        name = f"{base}.bin"
    return name

def unique_attachment_name(dir_path, filename):
    """같은 제품에 같은 이름의 파일을 두 번 올려도 기존 파일을 덮어쓰지 않도록,
    이미 있는 이름이면 뒤에 (2), (3)... 을 붙인다."""
    fname = sanitize_filename(filename)
    base, ext = os.path.splitext(fname)
    candidate = fname
    i = 1
    while os.path.exists(os.path.join(dir_path, candidate)):
        i += 1
        candidate = "%s(%d)%s" % (base, i, ext)
    return candidate
