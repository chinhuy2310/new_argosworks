import json
import re
import os
from datetime import datetime
from services.data_store import read_products, write_products, _save_lock
from utils.logging import access_log
from config import PRODUCT_ATTACH_DIR

def handle_product_save(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    
    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return

    from services.auth import can_modify_pim
    if not can_modify_pim(session):
        handler._send_json(403, {"ok": False, "error": "PIM 제품 및 가격 정보 수정 권한이 없습니다. (부서장(Manager) 또는 시스템 관리자만 가능)"})
        return

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    mode = (payload.get("mode") or "").strip()
    if mode not in ("create", "edit"):
        handler._send_json(400, {"ok": False, "error": "mode는 create 또는 edit이어야 합니다."})
        return
    
    from services.product_manager import validate_product_payload
    from services.data_store import next_product_id
    from services.audit_logger import log_audit

    price_changed = False
    old_price = None
    new_price = None

    with _save_lock:
        products = read_products()
        target = None
        if mode == "edit":
            pid = payload.get("id")
            target = next((p for p in products if p.get("id") == pid), None)
            if not target:
                handler._send_json(404, {"ok": False, "error": "제품을 찾을 수 없습니다."})
                return
            if payload.get("revision") != target.get("revision", 0):
                handler._send_json(409, {"ok": False,
                                       "error": "다른 변경이 먼저 저장되었습니다. 새로고침 후 다시 시도해주세요."})
                return

        cleaned, errors = validate_product_payload(payload, products, target.get("id") if target else None)
        if errors:
            handler._send_json(400, {"ok": False, "errors": errors})
            return

        now = datetime.now().isoformat()
        if mode == "create":
            product = {
                "id": next_product_id(),
                "model": cleaned.get("model", ""),
                "displayName": cleaned.get("displayName", ""),
                "family": cleaned.get("family", ""),
                "lifecycle": cleaned.get("lifecycle", "판매 중"),
                "summary": cleaned.get("summary", ""),
                "memo": cleaned.get("memo", ""),
                "category": cleaned.get("category", "일반"),
                "price": cleaned.get("price", 0),
                "currency": cleaned.get("currency", "KRW"),
                "specs": cleaned.get("specs", {}),
                "procurement": cleaned.get("procurement"),
                "attachments": [],
                "revision": 0,
                "createdAt": now, "updatedAt": now
            }
            products.append(product)
        else:
            product = target
            old_price = target.get("price")
            new_price = cleaned.get("price")
            if old_price != new_price:
                price_changed = True

            for key in ("model", "displayName", "family", "lifecycle", "summary", "memo", "category", "price", "currency"):
                if key in cleaned:
                    product[key] = cleaned[key]
            if "specs" in cleaned:
                product["specs"] = cleaned["specs"]
            if "procurement" in cleaned:
                product["procurement"] = cleaned["procurement"]
            product["revision"] = product.get("revision", 0) + 1
            product["updatedAt"] = now
        write_products(products)

    log_audit(
        session=session,
        ip=ip,
        action="PIM_PRICE_UPDATE" if price_changed else f"PIM_{mode.upper()}",
        target_type="pim",
        target_id=product.get("id"),
        details={
            "model": product.get("model"),
            "old_price": old_price,
            "new_price": product.get("price"),
            "currency": product.get("currency")
        }
    )

    access_log(ip, "product_" + mode, 200, product.get("model", ""))
    handler._send_json(200, {"ok": True, "product": product})

def handle_product_attachment_upload(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return

    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return

    from services.auth import can_modify_pim
    if not can_modify_pim(session):
        handler._send_json(403, {"ok": False, "error": "PIM 제품 및 첨부파일 관리 권한이 없습니다. (부서장(Manager) 또는 시스템 관리자만 가능)"})
        return

    content_type = handler.headers.get("Content-Type", "")
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        handler._send_json(400, {"ok": False, "error": "multipart/form-data 요청이 아닙니다."})
        return
    
    from utils.multipart import parse_multipart
    from utils.file_ops import unique_attachment_name
    fields, files = parse_multipart(raw_body, m.group(1))
    pid = (fields.get("id") or "").strip()
    if not pid:
        handler._send_json(400, {"ok": False, "error": "제품 id가 필요합니다."})
        return
    if not files:
        handler._send_json(400, {"ok": False, "error": "첨부할 파일을 선택해주세요."})
        return
    with _save_lock:
        products = read_products()
        product = next((p for p in products if p.get("id") == pid), None)
        if not product:
            handler._send_json(404, {"ok": False, "error": "제품을 찾을 수 없습니다."})
            return
        product_dir = os.path.join(PRODUCT_ATTACH_DIR, pid)
        os.makedirs(product_dir, exist_ok=True)
        attachments = product.setdefault("attachments", [])
        added = []
        from utils.image_optimizer import optimize_and_save_file
        for f in files:
            fname = unique_attachment_name(product_dir, f["filename"])
            dest = os.path.join(product_dir, fname)
            fsize = optimize_and_save_file(f["data"], dest)
            entry = {"name": fname, "size": fsize, "uploadedAt": datetime.now().isoformat()}
            attachments.append(entry)
            added.append(entry)
        write_products(products)
    access_log(ip, "product_attachment_upload", 200, "%s +%d" % (pid, len(added)))
    handler._send_json(200, {"ok": True, "product": product, "added": added})

def handle_product_attachment_delete(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return

    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return

    from services.auth import can_modify_pim
    if not can_modify_pim(session):
        handler._send_json(403, {"ok": False, "error": "PIM 제품 및 첨부파일 관리 권한이 없습니다. (부서장(Manager) 또는 시스템 관리자만 가능)"})
        return

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    pid = (payload.get("id") or "").strip()
    fname = (payload.get("name") or "").strip()
    with _save_lock:
        products = read_products()
        product = next((p for p in products if p.get("id") == pid), None)
        if not product:
            handler._send_json(404, {"ok": False, "error": "제품을 찾을 수 없습니다."})
            return
        attachments = product.get("attachments") or []
        match = next((a for a in attachments if a.get("name") == fname), None)
        if not match:
            handler._send_json(404, {"ok": False, "error": "첨부파일을 찾을 수 없습니다."})
            return
        product["attachments"] = [a for a in attachments if a.get("name") != fname]
        write_products(products)
        file_path = os.path.join(PRODUCT_ATTACH_DIR, pid, fname)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            from utils.logging import log_line
            log_line("첨부파일 삭제 실패(목록에서는 제거됨):", e)
    access_log(ip, "product_attachment_delete", 200, "%s %s" % (pid, fname))
    handler._send_json(200, {"ok": True, "product": product})


# ---------------------------------------------------------------------------
# Admin Product Categories & Spec Templates Management
# ---------------------------------------------------------------------------
from services.auth import is_admin_user, is_manager_or_admin

def _require_admin(handler, ip, action_name):
    session = handler._get_session_or_401()
    if session is None:
        return None
    if not is_manager_or_admin(session):
        access_log(ip, f"forbidden_{action_name}", 403, f"{session.get('name')}")
        handler._send_json(403, {
            "ok": False,
            "error": "관리자(Admin) 또는 부서장(Manager) 권한이 있는 사용자만 접근할 수 있습니다.",
            "forbidden": True
        })
        return None
    return session

def handle_get_product_categories_admin(handler, parsed, ip):
    session = _require_admin(handler, ip, "get_product_categories_admin")
    if session is None:
        return
    from services.data_store import read_product_categories
    cats = read_product_categories()
    handler._send_json(200, {"ok": True, "categories": cats})

def handle_product_category_save(handler, raw_body, ip):
    session = _require_admin(handler, ip, "save_product_category")
    if session is None:
        return
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    
    cat_id = (payload.get("id") or "").strip()
    name = (payload.get("name") or "").strip()
    spec_template = payload.get("spec_template") or []
    
    if not isinstance(spec_template, list):
        handler._send_json(400, {"ok": False, "error": "규격 템플릿 목록 형식이 올바르지 않습니다."})
        return

    from services.data_store import save_product_category, read_product_categories
    ok, res = save_product_category(cat_id, name, spec_template)
    if not ok:
        handler._send_json(400, {"ok": False, "error": res})
        return
    
    access_log(ip, "product_category_save", 200, f"{cat_id}: {name}")
    handler._send_json(200, {"ok": True, "categories": read_product_categories(), "id": res})

def handle_product_category_delete(handler, raw_body, ip):
    session = _require_admin(handler, ip, "delete_product_category")
    if session is None:
        return
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    
    cat_id = (payload.get("id") or "").strip()
    if not cat_id:
        handler._send_json(400, {"ok": False, "error": "카테고리 ID가 필요합니다."})
        return

    from services.data_store import delete_product_category, read_product_categories
    ok, err = delete_product_category(cat_id)
    if not ok:
        handler._send_json(400, {"ok": False, "error": err})
        return
    
    access_log(ip, "product_category_delete", 200, cat_id)
    handler._send_json(200, {"ok": True, "categories": read_product_categories()})
