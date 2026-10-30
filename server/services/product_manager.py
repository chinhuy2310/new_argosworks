import re
import os

PRODUCT_LIFECYCLES = ["판매 중", "단종 예정", "단종"]
PRODUCT_MODEL_RE = re.compile(r"^[0-9A-Za-z()._\- ]{1,100}$")
PRODUCT_IDNO_RE = re.compile(r"^\d{8}$")

from config import PRODUCT_CATEGORIES, SPEC_TEMPLATES
from services.data_store import get_product_categories_and_templates

def product_search_text(p):
    parts = [p.get("model", ""), p.get("displayName", ""), p.get("family", ""),
             p.get("summary", ""), p.get("category", "")]
    proc = p.get("procurement") or {}
    parts.append(proc.get("registeredName", ""))
    parts.append(proc.get("identificationNo", ""))
    for v in (p.get("specs") or {}).values():
        if v is not None:
            parts.append(str(v))
    return " ".join(str(part) for part in parts if part).lower()

def search_products(products, query):
    q = (query or "").strip().lower()
    if not q:
        return products
    tokens = q.split()
    out = []
    for p in products:
        text = product_search_text(p)
        if all(t in text for t in tokens):
            out.append(p)
    return out

def validate_product_payload(payload, existing_products, editing_id):
    """공통정보+조달정보 저장 전 검증. (정리된 값 dict, 에러 메시지) 중 하나를 돌려준다.
    빈칸은 "기존 값 유지"이므로, 이 함수는 신규 등록에서만 필수값을 강제하고,
    수정에서는 채워진 값만 돌려주고 나머지는 호출부에서 기존 값을 유지한다."""
    is_edit = editing_id is not None
    errors = []
    cleaned = {}

    def field(name, maxlen=None):
        raw = payload.get(name)
        if raw is None:
            return None  # 아예 안 보낸 필드 — 수정 시 기존 값 유지
        text = str(raw).strip()
        if text == "":
            return "" if not is_edit else None  # 수정 중 빈칸 입력 -> 기존 값 유지
        return text[:maxlen] if maxlen else text

    model = field("model", 100)
    if model is not None:
        if model == "":
            errors.append("제조 모델명을 입력해주세요.")
        elif not PRODUCT_MODEL_RE.match(model):
            errors.append("모델명은 영문자·숫자·공백·하이픈·밑줄·괄호·점만, 100자 이내로 입력해주세요.")
        else:
            dup = next((p for p in existing_products
                        if p.get("id") != editing_id and p.get("model", "").strip().lower() == model.lower()), None)
            if dup:
                errors.append("이미 등록된 모델명입니다: %s" % model)
            cleaned["model"] = model
    elif not is_edit:
        errors.append("제조 모델명을 입력해주세요.")

    display_name = field("displayName", 80)
    if display_name is not None:
        if display_name == "":
            errors.append("제품명(국문)을 입력해주세요.")
        else:
            cleaned["displayName"] = display_name
    elif not is_edit:
        errors.append("제품명(국문)을 입력해주세요.")

    family = field("family", 40)
    if family is not None:
        cleaned["family"] = family

    lifecycle = field("lifecycle", 20)
    if lifecycle is not None:
        if lifecycle and lifecycle not in PRODUCT_LIFECYCLES:
            errors.append("판매 상태는 판매 중/단종 예정/단종 중 하나여야 합니다.")
        else:
            cleaned["lifecycle"] = lifecycle or "판매 중"
    elif not is_edit:
        cleaned["lifecycle"] = "판매 중"

    summary = field("summary", 300)
    if summary is not None:
        cleaned["summary"] = summary

    memo = field("memo", 500)
    if memo is not None:
        cleaned["memo"] = memo

    # Dynamic categories & templates from DB
    dyn_categories, dyn_templates = get_product_categories_and_templates()
    if not dyn_categories:
        dyn_categories = PRODUCT_CATEGORIES
        dyn_templates = SPEC_TEMPLATES

    category = field("category", 50)
    if category is not None:
        if category and category not in dyn_categories:
            errors.append("카테고리는 " + "/".join(dyn_categories) + " 중 하나여야 합니다.")
        else:
            cleaned["category"] = category or (dyn_categories[0] if dyn_categories else "일반")
    elif not is_edit:
        cleaned["category"] = dyn_categories[0] if dyn_categories else "일반"

    # 제품 기본 가격 (Price)
    price_raw = payload.get("price")
    if price_raw is not None and str(price_raw).strip() != "":
        try:
            price = int(str(price_raw).strip())
            if price < 0 or price > 10**12:
                raise ValueError()
            cleaned["price"] = price
        except (TypeError, ValueError):
            errors.append("가격은 0 이상의 숫자로 입력해주세요.")
    elif not is_edit:
        cleaned["price"] = 0

    # 제품 통화 단위 (Currency: VND, USD, KRW)
    curr_raw = str(payload.get("currency") or "").strip().upper()
    if curr_raw in ("VND", "USD", "KRW"):
        cleaned["currency"] = curr_raw
    elif curr_raw:
        cleaned["currency"] = curr_raw[:10]
    elif not is_edit:
        cleaned["currency"] = "KRW"

    # 규격(specs)은 카테고리 템플릿 필드 + 커스텀 추가 필드 모두 수용
    specs_payload = payload.get("specs")
    if specs_payload is not None:
        if not isinstance(specs_payload, dict):
            errors.append("규격 정보 형식이 올바르지 않습니다.")
        else:
            specs = {}
            for k, v in specs_payload.items():
                k_clean = str(k).strip()[:80]
                if not k_clean:
                    continue
                v_clean = str(v).strip()[:300]
                if v_clean:
                    specs[k_clean] = v_clean
            cleaned["specs"] = specs

    proc_payload = payload.get("procurement")
    if proc_payload is None:
        pass  # 조달 정보 미포함 -> 기존 정보 유지(수정) 혹은 조달 없음(신규)
    elif proc_payload is False:
        cleaned["procurement"] = None  # 명시적으로 조달 연결 해제
    elif isinstance(proc_payload, dict):
        proc = {}

        def pfield(name, maxlen=None):
            raw = proc_payload.get(name)
            if raw is None:
                return None
            text = str(raw).strip()
            if text == "":
                return "" if not is_edit else None
            return text[:maxlen] if maxlen else text

        reg_name = pfield("registeredName", 60)
        idno = pfield("identificationNo", 8)
        is_active = bool(proc_payload.get("enabled") or (reg_name and reg_name.strip()) or (idno and idno.strip()))

        if is_active:
            if reg_name is not None:
                if reg_name == "" and not is_edit:
                    errors.append("조달 등록 식별명을 입력해주세요.")
                else:
                    proc["registeredName"] = reg_name

            if idno is not None:
                if idno == "":
                    if not is_edit:
                        errors.append("8자리 물품식별번호를 입력해주세요.")
                elif not PRODUCT_IDNO_RE.match(idno):
                    errors.append("물품식별번호는 숫자 8자리여야 합니다.")
                else:
                    dup = next((p for p in existing_products
                                if p.get("id") != editing_id
                                and (p.get("procurement") or {}).get("identificationNo") == idno), None)
                    if dup:
                        errors.append("이미 등록된 물품식별번호입니다: %s" % idno)
                    proc["identificationNo"] = idno

            configuration = pfield("configuration", 200)
            if configuration is not None:
                proc["configuration"] = configuration

            proc_price_raw = proc_payload.get("price")
            if proc_price_raw is not None and str(proc_price_raw).strip() != "":
                try:
                    price_val = int(str(proc_price_raw).strip())
                    if price_val >= 0:
                        proc["price"] = price_val
                        if "price" not in cleaned:
                            cleaned["price"] = price_val
                except (TypeError, ValueError):
                    pass
            elif "price" in cleaned:
                proc["price"] = cleaned["price"]
            elif not is_edit:
                proc["price"] = 0

            cleaned["procurement"] = proc
        else:
            # Not active: no procurement
            cleaned["procurement"] = None
    else:
        errors.append("조달 정보 형식이 올바르지 않습니다.")

    return cleaned, errors

# Canonical implementation is in services.search — re-exported here for compatibility
from services.search import product_as_search_record
