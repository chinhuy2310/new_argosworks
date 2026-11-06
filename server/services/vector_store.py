"""
vector_store.py — Voyage AI 기반 임베딩 및 Zero-Infrastructure 로컬 벡터 저장소
SQLite 파일(vector_store.sqlite)을 사용하여 추가 DB 서버 설치 없이 완벽한 의미 기반 검색(Semantic Search / RAG) 지원.
"""

import os
import json
import time
import math
import struct
import hashlib
import sqlite3
import urllib.request
import urllib.error
import threading
import re

from config import VECTOR_DB_PATH
from utils.logging import log_line

_db_lock = threading.Lock()
_sync_lock = threading.Lock()
_sync_pending = False
_sync_pending_lock = threading.Lock()
_worker_running = False


def get_db_connection():
    """SQLite 데이터베이스 연결 반환 (WAL 모드, busy_timeout 적용)"""
    conn = sqlite3.connect(VECTOR_DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_vector_db():
    """벡터 테이블 초기화"""
    with _db_lock:
        conn = get_db_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_embeddings (
                    doc_id TEXT PRIMARY KEY,
                    doc_type TEXT NOT NULL,
                    title TEXT,
                    content TEXT,
                    content_hash TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    dim INTEGER NOT NULL,
                    metadata_json TEXT,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_type ON document_embeddings(doc_type);")

            # Migration: Ensure embedding_model column exists
            cur = conn.execute("PRAGMA table_info(document_embeddings);")
            cols = {row["name"] for row in cur.fetchall()}
            if "embedding_model" not in cols:
                conn.execute("ALTER TABLE document_embeddings ADD COLUMN embedding_model TEXT;")
                conn.execute("UPDATE document_embeddings SET embedding_model = 'voyage-3-lite' WHERE embedding_model IS NULL;")

            conn.commit()
        finally:
            conn.close()


def pack_vector(vec):
    """부동소수점 리스트를 압축 바이너리(BLOB)로 변환"""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vector(blob, dim):
    """압축 바이너리(BLOB)를 부동소수점 튜플로 복원"""
    return struct.unpack(f"{dim}f", blob)


def cosine_similarity(v1, v2):
    """코사인 유사도 계산 (두 벡터의 내적 / (노름A * 노름B))"""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def get_voyage_api_keys(cfg):
    """
    Voyage/Embedding API 키 반환 (단일 키 리스트)
    """
    voyage_cfg = cfg.get("voyage") or {}
    raw = (
        voyage_cfg.get("api_key")
        or voyage_cfg.get("api_keys")
        or os.environ.get("VOYAGE_API_KEY")
        or os.environ.get("VOYAGE_API_KEYS")
        or ""
    )
    if isinstance(raw, list):
        return [k.strip() for k in raw if isinstance(k, str) and k.strip()]
    elif isinstance(raw, str):
        return [k.strip() for k in re.split(r"[,;\n\r]+", raw) if k.strip()]
    return []


def is_voyage_configured(cfg):
    """Voyage/임베딩 AI 설정 활성화 여부 확인 (오프라인/로컬 제공자는 API 키 없이도 활성화 가능)"""
    voyage_cfg = cfg.get("voyage") or {}
    if not voyage_cfg.get("enabled"):
        return False
    provider = (voyage_cfg.get("provider") or os.environ.get("VOYAGE_PROVIDER") or "voyage").lower().strip()
    if provider in ("ollama", "custom", "local", "vllm", "lmstudio"):
        base_url = (voyage_cfg.get("base_url") or os.environ.get("VOYAGE_BASE_URL") or "").strip()
        if base_url or provider == "ollama":
            return True
    keys = get_voyage_api_keys(cfg)
    return bool(keys)


def _mask_key_preview(k):
    """로그 출력용 API 키 안전 마스킹"""
    if not k:
        return ""
    if len(k) > 8:
        return f"{k[:4]}...{k[-4:]}"
    return "••••"


# ─────────────────────────────────────────────────────────────
# Embedding Provider Configs & Adapters
# ─────────────────────────────────────────────────────────────
EMBEDDING_PROVIDER_DEFAULTS = {
    "voyage": {
        "base_url": "https://api.voyageai.com/v1/embeddings",
        "default_model": "voyage-3-lite",
        "batch_size": 3,
        "format": "voyage"
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/embeddings",
        "default_model": "text-embedding-3-small",
        "batch_size": 20,
        "format": "openai"
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-embedding-001",
        "batch_size": 20,
        "format": "gemini"
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1/embeddings",
        "default_model": "nomic-embed-text",
        "batch_size": 10,
        "format": "openai"
    },
    "custom": {
        "base_url": "http://localhost:11434/v1/embeddings",
        "default_model": "nomic-embed-text",
        "batch_size": 10,
        "format": "openai"
    }
}


def get_embedding_provider_info(cfg):
    """설정된 임베딩 제공자, 모델, URL, 포맷 정보 반환"""
    v_cfg = cfg.get("voyage") or {}
    provider = (v_cfg.get("provider") or os.environ.get("VOYAGE_PROVIDER") or "voyage").lower().strip()
    defaults = EMBEDDING_PROVIDER_DEFAULTS.get(provider, EMBEDDING_PROVIDER_DEFAULTS["custom"])

    model = (v_cfg.get("model") or os.environ.get("VOYAGE_MODEL") or defaults.get("default_model") or "voyage-3-lite").strip()
    base_url = (v_cfg.get("base_url") or os.environ.get("VOYAGE_BASE_URL") or defaults.get("base_url") or "").strip()
    fmt = defaults.get("format", "openai")

    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "format": fmt,
        "batch_size": defaults.get("batch_size", 10)
    }


def get_embedding_identity(cfg):
    """
    임베딩 공간(Embedding Space)의 유일한 식별자(Fingerprint) 반환.
    동일한 모델명이라도 Provider나 Base URL(Ollama/Custom)이 다르면 다른 공간으로 취급함.
    형식:
      - Cloud (voyage, openai, gemini): 'provider:model' (예: 'openai:text-embedding-3-small')
      - Local/Custom (ollama, custom): 'provider:model@url_hash' (예: 'custom:nomic-embed-text@8f1a2b')
    """
    p_info = get_embedding_provider_info(cfg)
    prov = (p_info.get("provider") or "voyage").lower().strip()
    model = (p_info.get("model") or "voyage-3-lite").strip()
    base_url = (p_info.get("base_url") or "").strip().rstrip("/")

    if prov in ("custom", "ollama") and base_url:
        norm_url = base_url.lower()
        url_hash = hashlib.sha256(norm_url.encode("utf-8")).hexdigest()[:8]
        return f"{prov}:{model}@{url_hash}"

    return f"{prov}:{model}"


def is_matching_embedding_identity(saved_identity, current_identity, provider, model):
    """
    저장된 임베딩 식별자와 현재 식별자가 일치하는지 검사.
    하위 호환성: 레거시(콜론 없음, 예: 'voyage-3-lite')이고 provider가 'voyage'인 경우 호환 인정.
    """
    if not saved_identity:
        return False
    if saved_identity == current_identity:
        return True
    if ":" not in saved_identity and provider == "voyage" and saved_identity == model:
        return True
    return False


def get_search_embedding_identities(cfg):
    """
    검색 시 허용되는 embedding_model 값 목록 반환.
    현재 identity와 레거시 호환 값(콜론 없는 순수 model 이름)을 포함.
    """
    current_ident = get_embedding_identity(cfg)
    p_info = get_embedding_provider_info(cfg)
    prov = (p_info.get("provider") or "voyage").lower().strip()
    model = (p_info.get("model") or "voyage-3-lite").strip()

    allowed = [current_ident]
    if prov == "voyage":
        if model not in allowed:
            allowed.append(model)
        if "voyage-3-lite" not in allowed:
            allowed.append("voyage-3-lite")
    return allowed


def _execute_embedding_http(provider_info, key, texts, input_type="document", timeout=30):
    """
    단일 API Key로 지정된 제공자의 HTTP 임베딩 API를 1회 호출하고 임베딩 벡터 목록 반환.
    성공 시 (embeddings, None, None)
    실패 시 (None, status_code, error_message)
    """
    prov = provider_info["provider"]
    model = provider_info["model"]
    base_url = provider_info["base_url"]
    fmt = provider_info["format"]

    # 텍스트 전처리: 모델별 토큰 한도 보호 (Gemini 2048 tokens, OpenAI 8191 tokens, Voyage 32k)
    max_char_len = 3500 if (prov == "gemini" or fmt == "gemini") else 10000
    clean_texts = []
    for t in texts:
        s = (t or "").strip()
        if not s:
            s = "(내용 없음)"
        clean_texts.append(s[:max_char_len])

    if prov == "voyage" or fmt == "voyage":
        url = base_url or "https://api.voyageai.com/v1/embeddings"
        payload = {
            "input": clean_texts,
            "model": model,
            "input_type": input_type
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        }
    elif prov == "gemini" or fmt == "gemini":
        # Google Gemini batchEmbedContents API
        api_root = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        # 모델명에 models/ 접두사 확인
        m_name = model if "/" in model else f"models/{model}"
        url = f"{api_root}/{m_name}:batchEmbedContents?key={key}"
        task_type = "RETRIEVAL_QUERY" if input_type == "query" else "RETRIEVAL_DOCUMENT"
        requests_list = []
        for ct in clean_texts:
            requests_list.append({
                "model": m_name,
                "content": {"parts": [{"text": ct}]},
                "taskType": task_type
            })
        payload = {"requests": requests_list}
        headers = {"Content-Type": "application/json"}
    else:
        # OpenAI 표준 호환 (OpenAI, Local Ollama, Custom OpenAI-compatible)
        if not base_url:
            url = "https://api.openai.com/v1/embeddings"
        else:
            b = base_url.rstrip("/")
            if b.endswith("/embeddings"):
                url = b
            elif b.endswith("/v1"):
                url = f"{b}/embeddings"
            elif "/" not in b.split("://", 1)[-1]:
                url = f"{b}/v1/embeddings"
            else:
                url = f"{b}/embeddings"
        payload = {
            "input": clean_texts,
            "model": model
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))

            if prov == "gemini" or fmt == "gemini":
                # Gemini batchEmbedContents response: {"embeddings": [{"values": [...]}, ...]}
                embs = []
                for item in data.get("embeddings", []):
                    embs.append(item.get("values", []))
                return embs, None, None
            else:
                # OpenAI / Voyage format: {"data": [{"embedding": [...], "index": 0}, ...]}
                items = data.get("data", [])
                items.sort(key=lambda x: x.get("index", 0))
                return [it.get("embedding", []) for it in items], None, None

    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", "replace")
        return None, e.code, err_msg
    except Exception as e:
        return None, None, str(e)


def call_voyage_embeddings(cfg, texts, input_type="document", retry_on_429=True, timeout=30):
    """
    설정된 임베딩 제공자(Voyage, OpenAI, Gemini, Ollama, Custom)를 호출하여 임베딩 벡터 목록 반환
    - 다중 API 키 자동 로테이션(Round-Robin) 및 429 감지 시 즉각 전환(Failover)
    - retry_on_429: False일 경우(실시간 검색) 대기 없이 다른 키 즉시 시도 후 모두 실패 시 빈 리스트 반환
    - timeout: HTTP 타임아웃
    """
    keys = get_voyage_api_keys(cfg)
    provider_info = get_embedding_provider_info(cfg)
    prov = provider_info["provider"]
    if not keys:
        if prov in ("ollama", "custom", "local", "vllm", "lmstudio"):
            keys = ["local-key"]
        else:
            return []

    provider_info = get_embedding_provider_info(cfg)
    prov_label = provider_info["provider"].upper()

    max_attempts = 2 if retry_on_429 else 1

    for api_key in keys:
        masked_k = _mask_key_preview(api_key)
        for attempt in range(max_attempts):
            embeddings, err_code, err_msg = _execute_embedding_http(
                provider_info, api_key, texts, input_type=input_type, timeout=timeout
            )

            if embeddings is not None:
                return embeddings

            if err_code == 429:
                if retry_on_429 and attempt < max_attempts - 1:
                    wait_sec = 10.0 * (attempt + 1)
                    log_line(f"[{prov_label} Embedding] API 키 ({masked_k}) Rate Limit (429) 감지, {wait_sec}초 후 재시도...")
                    time.sleep(wait_sec)
                    continue
                else:
                    log_line(f"[{prov_label} Embedding] API 키 ({masked_k}) 429 감지 -> 다음 API 키로 즉시 Failover 전환합니다.")
                    break
            elif err_code in (401, 403):
                log_line(f"[{prov_label} Embedding] API 키 ({masked_k}) 인증 실패 ({err_code}) -> 다음 API 키로 전환합니다.")
                break
            else:
                log_line(f"[{prov_label} Embedding] 호출 실패 (HTTP {err_code}): {(err_msg or '')[:160]}")
                break

    return []


def embed_query(cfg, query_text):
    """검색 질문(Query)을 벡터로 변환 (사용자 검색 지연 방지: retry=False, timeout=5s)"""
    vecs = call_voyage_embeddings(cfg, [query_text], input_type="query", retry_on_429=False, timeout=5)
    return vecs[0] if vecs else None


# ─────────────────────────────────────────────────────────────
# 데이터 수집 및 인덱싱 동기화 (Sync)
# ─────────────────────────────────────────────────────────────

def _attachment_names(items):
    """File names from an attachments list. Accepts str items and dicts that use
    "filename" or "name" (different data sources use different keys); skips empties."""
    names = []
    for a in items or []:
        if not a:
            continue
        name = (a.get("filename") or a.get("name")) if isinstance(a, dict) else a
        name = str(name or "").strip()
        if name:
            names.append(name)
    return names


def _skip_bad_record(section, item, err):
    """One malformed record must not abort the whole vector sync: log it and move on."""
    ident = ""
    if isinstance(item, dict):
        ident = str(item.get("key") or item.get("id") or item.get("model") or "")
    log_line(f"[VectorStore] skip {section} {ident}: {type(err).__name__}: {err}")


def _collect_all_documents(cfg, strict=False, return_failed_sources=False):
    """JARVIS 내 모든 검색 대상 문서(기록, Jira 이슈, 제품 PIM, 캘린더)를 표준 형식으로 수집.
    strict=True 설정 시, 단일 행 오류나 소스 읽기 오류 발생 시 예외를 발생시켜
    부분 동기화로 인해 정상 문서의 벡터가 오삭제되는 것을 원천 방지한다.
    """
    from services.data_store import read_records, read_products, read_schedule, get_record_comments
    from services.jira_client import get_cached_jira_records

    docs = []
    failed_sources = set()

    # 1. 인수인계 및 업무 기록 (Local Cards / records)
    records_list = []
    try:
        records_list = read_records() or []
    except Exception as e:
        if strict:
            raise RuntimeError("Vector sync aborted: records source could not be read") from e
        failed_sources.add("record")
        log_line(f"[VectorStore] Failed to read records: {e}")

    for r in records_list:
        try:
            rid = r.get("id")
            if not rid:
                continue
            card_code = str(r.get("cardCode") or f"#{rid}").strip()
            title = (r.get("title") or "(제목 없음)").strip()
            org = r.get("org") or ""
            cat = r.get("category") or ""
            proj = r.get("project") or ""
            assignee = r.get("assignee") or ""
            assignee_email = r.get("assigneeEmail") or ""
            participants = r.get("participants") or ""
            status = r.get("status") or "진행"
            start_date = r.get("startDate") or r.get("date") or ""
            due_date = r.get("dueDate") or r.get("endDate") or start_date or ""
            date_str = f"{start_date} ~ {due_date}" if (start_date and due_date and start_date != due_date) else (start_date or r.get("date", ""))
            parent_key = r.get("parentKey") or ""
            summary = r.get("summary") or ""
            memo = r.get("memo") or ""
            tags = r.get("tags") or []
            attachments = r.get("attachments") or []
            jira = r.get("jira")

            # 댓글 및 업무 진행 이력 수집 (방어적 처리)
            comments_text = ""
            try:
                comments = get_record_comments(rid) or []
                if comments:
                    comments_lines = [
                        f"- ({str(c.get('created', ''))[:16]} {c.get('author', '작성자')}): {c.get('body', '')}"
                        for c in comments if isinstance(c, dict) and c.get("body")
                    ]
                    if comments_lines:
                        comments_text = "\n[댓글 및 진행 이력]\n" + "\n".join(comments_lines)
            except Exception as e:
                if strict:
                    raise RuntimeError("Vector sync aborted: record comments could not be read") from e
                comments_text = ""

            attach_names = _attachment_names(attachments)
            attach_text = f"\n첨부파일 목록: {', '.join(attach_names)}" if attach_names else ""
            parent_text = f" | 상위 작업: {parent_key}" if parent_key else ""
            part_text = f" | 참여자: {participants}" if participants else ""
            email_text = f" ({assignee_email})" if assignee_email else ""
            tags_text = f" | 태그: {', '.join(tags)}" if isinstance(tags, list) and tags else ""

            content = (
                f"[업무 카드: {card_code}] {title}\n"
                f"상태: {status} | 담당자: {assignee}{email_text}{part_text} | 부서: {org}\n"
                f"카테고리: {cat} | 관련 프로젝트/고객사: {proj}{parent_text}{tags_text}\n"
                f"진행 기간: {date_str}\n"
                f"업무 요약: {summary}\n"
                f"상세 내용 및 인수인계 메모:\n{memo}"
                f"{attach_text}"
                f"{comments_text}"
            ).strip()
            if isinstance(jira, dict) and jira.get("key"):
                content += f"\n연계 Jira 티켓: {jira.get('key')}"

            docs.append({
                "doc_id": f"record:{rid}",
                "doc_type": "record",
                "title": f"[{card_code}] {title}",
                "content": content,
                "metadata": {
                    "id": rid,
                    "cardCode": card_code,
                    "title": f"[{card_code}] {title}",
                    "org": org,
                    "dept_id": r.get("dept_id") or org,
                    "is_private": bool(r.get("is_private")),
                    "assignee_id": r.get("assignee_id"),
                    "assignee_name": assignee,
                    "assignee_email": assignee_email,
                    "category": cat,
                    "project": proj,
                    "assignee": assignee,
                    "participants": participants,
                    "status": status,
                    "date": start_date or r.get("date", ""),
                    "startDate": start_date,
                    "dueDate": due_date,
                    "summary": summary or memo[:200],
                    "jira": jira if isinstance(jira, dict) else None
                }
            })
        except Exception as _e:
            if strict:
                raise RuntimeError("Vector sync aborted: malformed record row") from _e
            _skip_bad_record('record', r, _e)

    # 2. Jira 동기화 이슈 (get_cached_jira_records)
    jira_records = []
    try:
        jira_cache = get_cached_jira_records(cfg) or {}
        jira_records = jira_cache.get("records") or []
    except Exception as e:
        if strict:
            raise RuntimeError("Vector sync aborted: Jira cache could not be read") from e
        failed_sources.add("jira")
        log_line(f"[VectorStore] Failed to read Jira cache: {e}")

    for j in jira_records:
        try:
            jira_info = j.get("jira") if isinstance(j.get("jira"), dict) else {}
            key = jira_info.get("key") or str(j.get("id", ""))
            if not key:
                continue
            title = (j.get("title") or "(제목 없음)").strip()
            org = j.get("org") or ""
            cat = j.get("category") or ""
            assignee = j.get("assignee") or ""
            summary = j.get("summary") or ""
            status = j.get("statusName") or ""
            parent_key = j.get("parentKey") or ""
            participants = j.get("participants") or ""

            comments = j.get("comments") or []
            comments_text = ""
            if comments:
                comments_lines = [
                    f"- ({str(c.get('created', ''))[:16]} {c.get('author', '')}): {c.get('body', '')}"
                    for c in comments if isinstance(c, dict) and c.get("body")
                ]
                if comments_lines:
                    comments_text = "\n[댓글 및 진행 이력]\n" + "\n".join(comments_lines)

            attach_names = _attachment_names(j.get("attachments"))
            attach_text = f"\n첨부파일 목록: {', '.join(attach_names)}" if attach_names else ""
            parent_text = f" | 상위 작업: {parent_key}" if parent_key else ""
            part_text = f" | 참여자: {participants}" if participants else ""

            content = (
                f"[Jira {key}] {title}\n"
                f"상태: {status} | 담당자: {assignee}{part_text} | 부서: {org}\n"
                f"카테고리: {cat}{parent_text}\n"
                f"상세 내용: {summary}"
                f"{attach_text}"
                f"{comments_text}"
            ).strip()

            docs.append({
                "doc_id": f"jira:{key}",
                "doc_type": "jira",
                "title": f"[{key}] {title}",
                "content": content,
                "metadata": {
                    "id": j.get("id"),
                    "cardCode": key,
                    "title": f"[{key}] {title}",
                    "org": org,
                    "category": cat,
                    "assignee": assignee,
                    "participants": participants,
                    "date": j.get("date", ""),
                    "summary": summary,
                    "status": status,
                    "jira": j.get("jira")
                }
            })
        except Exception as _e:
            if strict:
                raise RuntimeError("Vector sync aborted: malformed Jira row") from _e
            _skip_bad_record('jira', j, _e)

    # 3. 제품 정보 (PIM) - 사내 관리 제품 및 공식 라이브 제품 모두 벡터 인덱싱
    products_list = []
    try:
        products_list = read_products(include_external=True) or []
    except Exception as e:
        if strict:
            raise RuntimeError("Vector sync aborted: products source could not be read") from e
        failed_sources.add("product")
        log_line(f"[VectorStore] Failed to read products: {e}")

    for p in products_list:
        try:
            pid = p.get("id")
            if not pid:
                continue
            model = p.get("model") or ""
            name = p.get("displayName") or model or "(이름 없음)"
            cat = p.get("category") or ""
            family = p.get("family") or ""
            lifecycle = p.get("lifecycle") or "판매 중"
            source = p.get("source") or "internal"
            is_live = (source == "vision119" or source == "external")

            desc_parts = []
            if p.get("summary"):
                desc_parts.append(f"핵심 요약: {p.get('summary')}")
            if p.get("memo"):
                desc_parts.append(f"상세 메모/내부 참고사항: {p.get('memo')}")
            desc = "\n".join(desc_parts) if desc_parts else ""

            # ⚠️ 가격 정보는 임베딩 콘텐츠에 절대 포함하지 않는다 (의미 검색을 통한 가격 유출 방지).
            # 가격은 can_view_pim_price 권한을 검사하는 PIM API / 챗 도구에서만 마스킹 후 제공한다.
            proc = p.get("procurement") if isinstance(p.get("procurement"), dict) else {}
            proc_str = ""
            if proc and proc.get("identificationNo"):
                proc_str = f"조달정보: 식별번호 {proc.get('identificationNo')} | 품명 {proc.get('registeredName', '')}"

            specs_dict = p.get("specs") if isinstance(p.get("specs"), dict) else {}
            specs_lines = [f"- {k}: {v}" for k, v in specs_dict.items() if v]
            specs_str = "\n".join(specs_lines) if specs_lines else "등록된 세부 규격 없음"

            attach_names = _attachment_names(p.get("attachments"))
            attach_str = f"첨부자료: {', '.join(attach_names)}" if attach_names else ""

            meta_rows = [f"제품구분: {'공식 카탈로그' if is_live else '사내 관리 제품'}", f"모델명: {model}", f"제품명: {name}", f"카테고리: {cat} (패밀리: {family}) | 수명주기: {lifecycle}"]
            if desc:
                meta_rows.append(f"설명 및 소개:\n{desc}")
            if proc_str:
                meta_rows.append(proc_str)
            if attach_str:
                meta_rows.append(attach_str)
            meta_rows.append(f"세부 규격 사양:\n{specs_str}")

            content = "\n".join(meta_rows).strip()

            docs.append({
                "doc_id": f"product:{pid}",
                "doc_type": "product",
                "title": f"[제품] {name} ({model})",
                "content": content,
                "metadata": {
                    "id": f"pim-{pid}",
                    "title": f"[제품] {name} ({model})",
                    "org": "공식카탈로그" if is_live else "lab",
                    "category": cat,
                    "summary": (p.get("summary") or p.get("memo") or "")[:200],
                    "date": (p.get("updatedAt") or "")[:10],
                    "source": source
                }
            })
        except Exception as _e:
            if strict:
                raise RuntimeError("Vector sync aborted: malformed product row") from _e
            _skip_bad_record('product', p, _e)

    # 4. 일정 (schedule.json)
    schedule_list = []
    try:
        schedule_list = read_schedule() or []
    except Exception as e:
        if strict:
            raise RuntimeError("Vector sync aborted: schedule source could not be read") from e
        failed_sources.add("schedule")
        log_line(f"[VectorStore] Failed to read schedule: {e}")

    for s in schedule_list:
        try:
            sid = s.get("id")
            if not sid:
                continue
            title = s.get("title") or ""
            owner = s.get("ownerName") or ""
            org = s.get("ownerOrg") or ""
            stype = s.get("type") or ""
            memo = s.get("memo") or ""
            sdate = s.get("startDate") or ""
            edate = s.get("endDate") or sdate
            parts = s.get("participants") or []
            parts_names = [p.get("name") if isinstance(p, dict) else str(p) for p in parts if p]
            parts_str = f" | 참석자: {', '.join(parts_names)}" if parts_names else ""

            content = (
                f"[일정: {stype}] {title}\n"
                f"담당자: {owner} ({org}){parts_str}\n"
                f"기간: {sdate} ~ {edate}\n"
                f"메모: {memo}"
            ).strip()

            docs.append({
                "doc_id": f"schedule:{sid}",
                "doc_type": "schedule",
                "title": f"[일정] {title} ({owner})",
                "content": content,
                "metadata": {
                    "id": sid,
                    "title": f"[{stype}] {title} ({owner})",
                    "org": org,
                    "dept_id": org,
                    "ownerName": owner,
                    "ownerOrg": org,
                    "participants": parts_names,
                    "category": stype,
                    "summary": memo,
                    "date": sdate
                }
            })
        except Exception as _e:
            if strict:
                raise RuntimeError("Vector sync aborted: malformed schedule row") from _e
            _skip_bad_record('schedule', s, _e)

    if return_failed_sources:
        return docs, failed_sources
    return docs


def check_vector_sync_status(cfg):
    """벡터 동기화 상태 검사 (API 호출 없이 로컬 DB와 해시 비교)"""
    if not is_voyage_configured(cfg):
        return {"ok": False, "reason": "voyage_not_configured"}

    init_vector_db()
    current_ident = get_embedding_identity(cfg)
    p_info = get_embedding_provider_info(cfg)
    prov = (p_info.get("provider") or "voyage").lower().strip()
    model_name = (p_info.get("model") or "voyage-3-lite").strip()

    docs = _collect_all_documents(cfg)
    if not docs:
        return {
            "ok": True,
            "current_model": current_ident,
            "total": 0,
            "synced": 0,
            "missing": 0,
            "diff_model": 0,
            "is_fully_synced": True,
            "needs_model_migration_warning": False
        }

    conn = get_db_connection()
    try:
        existing = {}
        for row in conn.execute("SELECT doc_id, content_hash, embedding_model FROM document_embeddings;"):
            existing[row["doc_id"]] = {
                "hash": row["content_hash"],
                "model": row["embedding_model"] or "voyage-3-lite"
            }

        synced = 0
        diff_model = 0
        missing = 0

        for d in docs:
            chash = hashlib.sha256(d["content"].encode("utf-8")).hexdigest()
            doc_id = d["doc_id"]
            if doc_id in existing:
                rec = existing[doc_id]
                if not is_matching_embedding_identity(rec["model"], current_ident, prov, model_name):
                    diff_model += 1
                    missing += 1
                elif rec["hash"] != chash:
                    missing += 1
                else:
                    synced += 1
            else:
                missing += 1

        return {
            "ok": True,
            "current_model": current_ident,
            "total": len(docs),
            "synced": synced,
            "missing": missing,
            "diff_model": diff_model,
            "is_fully_synced": missing == 0,
            "needs_model_migration_warning": diff_model > 0
        }
    finally:
        conn.close()


def sync_all_vectors(cfg, force=False):
    """
    모든 문서의 벡터 임베딩을 점진적(Incremental)으로 동기화.
    내용의 해시(SHA256) 및 모델 일치 여부를 비교하여 변경되지 않은 문서는 API 호출을 생략(0비용).
    """
    if not is_voyage_configured(cfg):
        return {"ok": False, "reason": "voyage_not_configured"}

    if not _sync_lock.acquire(blocking=False):
        return {"ok": False, "reason": "already_syncing"}

    try:
        t0 = time.time()
        init_vector_db()
        current_ident = get_embedding_identity(cfg)
        p_info = get_embedding_provider_info(cfg)
        prov = (p_info.get("provider") or "voyage").lower().strip()
        model_name = (p_info.get("model") or "voyage-3-lite").strip()

        try:
            docs, failed_sources = _collect_all_documents(cfg, strict=True, return_failed_sources=True)
        except RuntimeError as sync_err:
            log_line(f"[Vector Store] Strict 동기화 중단 (문서 삭제 방지): {sync_err}")
            return {"ok": False, "error": str(sync_err)}
        if not docs and not failed_sources:
            return {"ok": True, "indexed": 0, "skipped": 0, "total": 0, "current_model": current_ident}

        conn = get_db_connection()
        try:
            existing = {}
            for row in conn.execute("SELECT doc_id, content_hash, embedding_model FROM document_embeddings;"):
                existing[row["doc_id"]] = {
                    "hash": row["content_hash"],
                    "model": row["embedding_model"] or "voyage-3-lite"
                }

            to_embed = []
            skipped = 0
            failed_doc_ids = []

            for d in docs:
                chash = hashlib.sha256(d["content"].encode("utf-8")).hexdigest()
                d["content_hash"] = chash
                doc_id = d["doc_id"]
                is_model_match = doc_id in existing and is_matching_embedding_identity(existing[doc_id]["model"], current_ident, prov, model_name)
                if not force and is_model_match and existing[doc_id]["hash"] == chash:
                    skipped += 1
                else:
                    to_embed.append(d)

            indexed = 0
            if to_embed:
                keys = get_voyage_api_keys(cfg)
                num_keys = max(1, len(keys))
                p_info = get_embedding_provider_info(cfg)
                BATCH_SIZE = p_info.get("batch_size", 10)
                # Voyage AI는 3 RPM 제한이 있어 22s/N 간격 필요. OpenAI/Gemini는 Rate limit이 넉넉하므로 0.5초 또는 빠른 간격 적용
                if p_info["provider"] == "voyage":
                    inter_batch_delay = max(1.0, 22.0 / num_keys)
                else:
                    inter_batch_delay = 0.5
                log_line(f"[Vector Store] 색인 시작: {p_info['provider'].upper()} ({current_ident}) 총 {len(to_embed)}건, 등록된 API Key {num_keys}개, 배치 크기 {BATCH_SIZE}, 간격 {inter_batch_delay:.1f}초")

                for i in range(0, len(to_embed), BATCH_SIZE):
                    if i > 0 and inter_batch_delay > 0:
                        time.sleep(inter_batch_delay)
                    batch = to_embed[i:i + BATCH_SIZE]
                    texts = [b["content"] for b in batch]
                    embeddings = call_voyage_embeddings(cfg, texts, input_type="document")

                    if not embeddings or len(embeddings) != len(batch):
                        # Lỗi cả batch (ví dụ: có tài liệu quá dài gây HTTP 400).
                        # Để tránh "poison pill" kéo theo cả lô tài liệu lành bị loại bỏ vĩnh viễn,
                        # tự động chuyển sang fallback thử từng tài liệu đơn lẻ.
                        if len(batch) > 1:
                            log_line(f"[Vector Store] 배치 임베딩 실패 (batch size: {len(batch)}), 개별 재시도(Single-item fallback) 진행...")
                            batch_success = []
                            batch_embeddings = []
                            for single_item in batch:
                                s_emb = call_voyage_embeddings(cfg, [single_item["content"]], input_type="document")
                                if s_emb and len(s_emb) == 1:
                                    batch_success.append(single_item)
                                    batch_embeddings.append(s_emb[0])
                                else:
                                    log_line(f"[Vector Store] 개별 문서 임베딩 실패로 건너뜀 (doc_id={single_item.get('doc_id')})")
                                    failed_doc_ids.append(single_item.get("doc_id"))
                            batch = batch_success
                            embeddings = batch_embeddings
                        else:
                            log_line(f"[Vector Store] 단일 문서 임베딩 실패로 건너뜀 (doc_id={batch[0].get('doc_id')})")
                            failed_doc_ids.append(batch[0].get("doc_id"))
                            continue

                    if not embeddings:
                        continue

                    dim = len(embeddings[0])
                    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

                    with _db_lock:
                        for item, vec in zip(batch, embeddings):
                            v_blob = pack_vector(vec)
                            conn.execute("""
                                INSERT OR REPLACE INTO document_embeddings 
                                (doc_id, doc_type, title, content, content_hash, vector_blob, dim, metadata_json, updated_at, embedding_model)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                item["doc_id"],
                                item["doc_type"],
                                item["title"],
                                item["content"],
                                item["content_hash"],
                                v_blob,
                                dim,
                                json.dumps(item["metadata"], ensure_ascii=False),
                                now_str,
                                current_ident
                            ))
                        conn.commit()
                    indexed += len(batch)
            # Remove deleted / obsolete documents from vector store (excluding sources that failed to load)
            current_doc_ids = {d["doc_id"] for d in docs}
            stale_doc_ids = []
            for doc_id in existing:
                if doc_id not in current_doc_ids:
                    dtype = doc_id.split(":", 1)[0]
                    if dtype in failed_sources:
                        continue
                    stale_doc_ids.append(doc_id)
            if stale_doc_ids:
                with _db_lock:
                    for s_id in stale_doc_ids:
                        conn.execute("DELETE FROM document_embeddings WHERE doc_id = ?;", (s_id,))
                    conn.commit()
                log_line(f"[Vector Store] 삭제된 문서 {len(stale_doc_ids)}건 색인 정리 완료")

            duration = round(time.time() - t0, 2)
            if failed_doc_ids:
                log_line(f"[Vector Store] 동기화 부분 실패: 전체 {len(docs)}건 중 {len(failed_doc_ids)}건 임베딩 실패 ({duration}초, 모델: {current_ident})")
                return {
                    "ok": False,
                    "partial": True,
                    "error": f"동기화 부분 실패: 전체 {len(docs)}건 중 {len(failed_doc_ids)}건 임베딩 실패",
                    "indexed": indexed,
                    "skipped": skipped,
                    "failed": len(failed_doc_ids),
                    "failed_doc_ids": failed_doc_ids,
                    "total": len(docs),
                    "duration_sec": duration,
                    "current_model": current_ident
                }

            log_line(f"[Vector Store] 동기화 완료: 신규 {indexed}건, 스킵 {skipped}건, 총 {len(docs)}건 ({duration}초, 모델: {current_ident})")
            return {
                "ok": True,
                "indexed": indexed,
                "skipped": skipped,
                "total": len(docs),
                "duration_sec": duration,
                "current_model": current_ident
            }
        finally:
            conn.close()
    finally:
        _sync_lock.release()
        with _sync_pending_lock:
            has_pending = _sync_pending
        if has_pending:
            trigger_async_vector_sync(cfg)


def trigger_async_vector_sync(cfg):
    """백그라운드 스레드에서 점진적(Incremental) 벡터 색인 비동기 실행 (coalesced coordinator)"""
    global _sync_pending, _worker_running
    if not is_voyage_configured(cfg):
        return
    with _sync_pending_lock:
        _sync_pending = True
        if _worker_running:
            return
        _worker_running = True
    import threading
    threading.Thread(target=_run_coalesced_sync, args=(cfg,), daemon=True).start()


def _run_coalesced_sync(cfg):
    global _sync_pending, _worker_running
    try:
        while True:
            with _sync_pending_lock:
                _sync_pending = False
            sync_all_vectors(cfg)
            with _sync_pending_lock:
                if not _sync_pending:
                    break
    finally:
        with _sync_pending_lock:
            _worker_running = False
            if _sync_pending:
                trigger_async_vector_sync(cfg)


# ---------------------------------------------------------------------------
# 문서 단위 RBAC — 의미 검색 결과에도 레코드/일정과 동일한 권한 기준을 적용한다
# ---------------------------------------------------------------------------
_PRICE_TEXT_RE = re.compile(
    r"(기준\s*가격|단가|판매가|공급가|원가|도매가|price|unit\s*price)\s*[:：]?\s*[\d,\.]+\s*(원|KRW|USD|VND|JPY|CNY|EUR)?",
    re.IGNORECASE,
)


def _mask_price_text(text, max_len=None):
    """권한 없는 사용자에게 반환되는 텍스트에서 가격 패턴을 마스킹한다."""
    if not text:
        return ""
    masked = _PRICE_TEXT_RE.sub("[가격 비공개]", str(text))
    if max_len:
        masked = masked[:max_len]
    return masked


def build_doc_permission_context(session):
    """문서 권한 판정에 필요한 컨텍스트(부서맵/일정 캐시/가격권한)를 1회만 구성한다."""
    from services.auth import build_user_dept_map

    return {
        "session": session,
        "dept_map": build_user_dept_map(),
        "schedule_by_id": None,
        "allow_price": None,
    }


def _legacy_schedule_event(meta, ctx):
    """레거시 인덱스(ownerName 없음) 호환: 원본 일정에서 소유자/참석자 정보를 보완한다."""
    event = dict(meta or {})
    if event.get("ownerName") or ctx is None:
        return event
    if ctx.get("schedule_by_id") is None:
        by_id = {}
        try:
            from services.data_store import read_schedule
            for ev in read_schedule():
                by_id[str(ev.get("id"))] = ev
        except Exception:
            by_id = {}
        ctx["schedule_by_id"] = by_id
    src = ctx["schedule_by_id"].get(str(meta.get("id"))) or {}
    for k in ("ownerName", "ownerOrg", "participants"):
        if src.get(k) and not event.get(k):
            event[k] = src[k]
    if not event.get("org") and src.get("ownerOrg"):
        event["org"] = src["ownerOrg"]
    return event


def can_view_vector_doc(session, doc_type, meta, ctx=None):
    """doc_type별 열람 권한 판정 (record / jira / schedule / product)."""
    from services.auth import can_view_record, can_view_schedule_event

    meta = meta or {}
    if doc_type == "record":
        r_id = meta.get("id") or meta.get("record_id")
        if r_id:
            try:
                from db import get_one
                live_r = get_one(
                    """SELECT id, card_code, title, dept_id, is_private,
                              assignee_id, assignee_name, assignee_email, participants
                       FROM records WHERE id = ? LIMIT 1""",
                    (r_id,)
                )
                if not live_r:
                    # Deleted record: fail-closed
                    return False
                rec = dict(meta)
                rec["id"] = live_r.get("id")
                rec["cardCode"] = live_r.get("card_code") or meta.get("cardCode")
                rec["title"] = live_r.get("title") or meta.get("title")
                rec["dept_id"] = live_r.get("dept_id")
                rec["org"] = live_r.get("dept_id")
                rec["is_private"] = bool(live_r.get("is_private"))
                rec["assignee_id"] = live_r.get("assignee_id")
                rec["assignee_name"] = live_r.get("assignee_name") or ""
                rec["assignee"] = live_r.get("assignee_name") or ""
                rec["assignee_email"] = live_r.get("assignee_email") or ""
                rec["assigneeEmail"] = live_r.get("assignee_email") or ""

                raw_p = live_r.get("participants")
                if raw_p:
                    if isinstance(raw_p, str):
                        try:
                            rec["participants"] = json.loads(raw_p)
                        except Exception:
                            rec["participants"] = []
                    else:
                        rec["participants"] = raw_p
                else:
                    rec["participants"] = []
                return can_view_record(session, rec)
            except Exception:
                # On query error: fail-closed to prevent leaking private data based on stale metadata
                return False
        return can_view_record(session, meta)

    if doc_type == "jira":
        # Jira 캐시 레코드도 DB의 최신 정보를 우선 확인하고, 없는 경우 meta 기반으로 열람 권한을 판정한다.
        jira_info = meta.get("jira") if isinstance(meta.get("jira"), dict) else {}
        jira_key = (meta.get("cardCode") or jira_info.get("key") or "").strip()
        if not jira_key:
            raw_id = str(meta.get("id") or "").strip()
            jira_key = raw_id[5:] if raw_id.startswith("jira-") else raw_id
        if jira_key:
            try:
                from db import get_one
                live_row = get_one(
                    "SELECT raw_json FROM jira_issues WHERE UPPER(jira_key) = UPPER(?) LIMIT 1",
                    (jira_key,)
                )
                if live_row and live_row.get("raw_json"):
                    live_rec = json.loads(live_row["raw_json"])
                    if isinstance(live_rec, dict):
                        rec = dict(live_rec)
                        rec["assignee_name"] = rec.get("assignee") or rec.get("assignee_name") or ""
                        rec["assignee_email"] = rec.get("assigneeEmail") or rec.get("assignee_email") or ""
                        rec["dept_id"] = rec.get("dept_id") or rec.get("org") or ""
                        rec["org"] = rec.get("org") or rec.get("dept_id") or ""
                        rec["is_private"] = bool(rec.get("is_private"))
                        return can_view_record(session, rec)
            except Exception:
                pass
        rec = dict(meta)
        rec["assignee_name"] = meta.get("assignee_name") or meta.get("assignee") or ""
        rec["assignee"] = meta.get("assignee") or ""
        rec["dept_id"] = meta.get("dept_id") or meta.get("org") or ""
        rec["org"] = meta.get("org") or ""
        rec["is_private"] = bool(meta.get("is_private"))
        return can_view_record(session, rec)

    if doc_type == "schedule":
        event = _legacy_schedule_event(meta, ctx)
        return can_view_schedule_event(session, event, user_dept_map=(ctx or {}).get("dept_map"))

    # 제품(PIM) 문서는 전 사용자 공개 — 가격은 색인 콘텐츠에서 제거/마스킹된다.
    return True


def can_view_vector_price(session, ctx=None):
    """PIM 가격 열람 권한 (검색 결과 텍스트 마스킹용, 1회 캐시)."""
    if session is None:
        return True
    if ctx is not None and ctx.get("allow_price") is not None:
        return ctx["allow_price"]
    from services.auth import can_view_pim_price
    allowed = can_view_pim_price(session)
    if ctx is not None:
        ctx["allow_price"] = allowed
    return allowed


_NUMPY_AVAILABLE = None

def _is_numpy_available():
    global _NUMPY_AVAILABLE
    if _NUMPY_AVAILABLE is None:
        try:
            import numpy  # noqa: F401
            _NUMPY_AVAILABLE = True
        except ImportError:
            _NUMPY_AVAILABLE = False
    return _NUMPY_AVAILABLE


def search_vector_store(cfg, query_text, limit=6, min_similarity=0.42, session=None):
    """
    자연어 질문(query_text)을 기반으로 가장 관련성 높은 문서를 코사인 유사도로 검색.
    반환: 유사도 내림차순 정렬된 문서 리스트 (metadata 및 similarity 포함)
    """
    if not is_voyage_configured(cfg) or not query_text.strip():
        return []

    # 1. 쿼리 임베딩
    query_vec = embed_query(cfg, query_text)
    if not query_vec:
        return []

    # 2. SQLite에서 질의 벡터 차원과 일치하는 벡터 조회 (차원 불일치 무음 0점 방지 및 스케일 최적화)
    init_vector_db()
    conn = get_db_connection()
    q_dim = len(query_vec)

    allowed_models = get_search_embedding_identities(cfg)
    p_info = get_embedding_provider_info(cfg)
    prov = (p_info.get("provider") or "voyage").lower().strip()
    placeholders = ",".join("?" for _ in allowed_models)
    null_clause = "OR embedding_model IS NULL" if prov == "voyage" else ""

    try:
        sql = f"""
            SELECT doc_id, doc_type, title, content, vector_blob, dim, metadata_json
            FROM document_embeddings
            WHERE dim = ? AND (embedding_model IN ({placeholders}) {null_clause});
        """
        rows = conn.execute(sql, [q_dim] + allowed_models).fetchall()

        if not rows:
            # 저장된 다른 차원의 벡터가 있는지 검사하여 모델 변경 경고
            total_cnt = conn.execute("SELECT COUNT(*) FROM document_embeddings;").fetchone()[0]
            if total_cnt > 0:
                log_line(f"[Vector Store] 경고: 쿼리 임베딩 차원({q_dim})과 일치하는 문서가 없습니다. (총 {total_cnt}개 문서는 다른 차원 모델로 생성됨 -> /api/settings 또는 자동 동기화로 재색인이 필요합니다)")
            return []

        perm_ctx = build_doc_permission_context(session) if session is not None else None

        # 1. 고속 NumPy C-BLAS 벡터화 검색 (선택적 가속: O(1) 메모리 재사용 & SIMD 병렬 내적 계산)
        if _is_numpy_available():
            try:
                import numpy as np

                query_arr = np.array(query_vec, dtype=np.float32)
                q_norm = float(np.linalg.norm(query_arr))
                if q_norm > 0:
                    query_arr /= q_norm

                all_bytes = b"".join(r["vector_blob"] for r in rows)
                n_rows = len(rows)
                doc_matrix = np.frombuffer(all_bytes, dtype=np.float32).reshape(n_rows, q_dim)

                doc_norms = np.linalg.norm(doc_matrix, axis=1)
                doc_norms[doc_norms == 0] = 1e-12
                sims = np.dot(doc_matrix, query_arr) / doc_norms

                match_mask = sims >= min_similarity
                candidate_indices = np.where(match_mask)[0]
                if candidate_indices.size == 0:
                    return []

                # 유사도 내림차순 정렬
                sorted_indices = candidate_indices[np.argsort(-sims[candidate_indices])]

                results = []
                for idx in sorted_indices:
                    row = rows[idx]
                    sim = float(sims[idx])

                    try:
                        meta = json.loads(row["metadata_json"] or "{}")
                    except Exception:
                        meta = {}

                    # Privacy isolation: doc_type별 RBAC (record / jira / schedule)
                    if session is not None and not can_view_vector_doc(session, row["doc_type"], meta, perm_ctx):
                        continue
                    elif session is None:
                        # Unauthenticated search: never expose private records or internal schedules
                        if row["doc_type"] in ("record", "jira") and bool(meta.get("is_private")):
                            continue
                        if row["doc_type"] == "schedule":
                            continue

                    can_view_price = (
                        can_view_vector_price(session, perm_ctx) if session is not None else False
                    )
                    summary_text = meta.get("summary") or ""
                    if not summary_text and row["doc_type"] != "product":
                        summary_text = row["content"][:200]
                    evidence_text = str(row["content"] or "")
                    if row["doc_type"] == "product" and not can_view_price:
                        summary_text = _mask_price_text(summary_text, max_len=200)
                        evidence_text = _mask_price_text(evidence_text)

                    results.append({
                        "id": meta.get("id") or row["doc_id"],
                        "doc_id": row["doc_id"],
                        "source_id": row["doc_id"],
                        "doc_type": row["doc_type"],
                        "title": row["title"],
                        "similarity": round(sim, 4),
                        "summary": summary_text,
                        "evidence": evidence_text[:1200],
                        "org": meta.get("org") or "",
                        "category": meta.get("category") or "",
                        "date": meta.get("date") or "",
                        "assignee": meta.get("assignee") or "",
                        "jira": meta.get("jira")
                    })
                    if len(results) >= limit:
                        break

                return results
            except Exception as np_err:
                log_line("[Vector Store] NumPy 고속 검색 실패 또는 예외, 기본 순차 루프로 전환:", np_err)

        # 2. NumPy 미사용 환경 또는 예외 발생 시 안전한 순차 루프(Fallback)
        import heapq
        top_heap = []
        counter = 0

        for row in rows:
            blob = row["vector_blob"]
            doc_vec = unpack_vector(blob, q_dim)
            sim = cosine_similarity(query_vec, doc_vec)

            if sim >= min_similarity:
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                except Exception:
                    meta = {}

                # Privacy isolation: doc_type별 RBAC (record / jira / schedule)
                if session is not None and not can_view_vector_doc(session, row["doc_type"], meta, perm_ctx):
                    continue
                elif session is None:
                    # Unauthenticated search: never expose private records or internal schedules
                    if row["doc_type"] in ("record", "jira") and bool(meta.get("is_private")):
                        continue
                    if row["doc_type"] == "schedule":
                        continue

                counter += 1

                can_view_price = (
                    can_view_vector_price(session, perm_ctx) if session is not None else False
                )
                summary_text = meta.get("summary") or ""
                if not summary_text and row["doc_type"] != "product":
                    summary_text = row["content"][:200]
                evidence_text = str(row["content"] or "")
                if row["doc_type"] == "product" and not can_view_price:
                    summary_text = _mask_price_text(summary_text, max_len=200)
                    evidence_text = _mask_price_text(evidence_text)

                item = {
                    "id": meta.get("id") or row["doc_id"],
                    "doc_id": row["doc_id"],
                    "source_id": row["doc_id"],
                    "doc_type": row["doc_type"],
                    "title": row["title"],
                    "similarity": round(sim, 4),
                    "summary": summary_text,
                    "evidence": evidence_text[:1200],
                    "org": meta.get("org") or "",
                    "category": meta.get("category") or "",
                    "date": meta.get("date") or "",
                    "assignee": meta.get("assignee") or "",
                    "jira": meta.get("jira")
                }

                if len(top_heap) < limit:
                    heapq.heappush(top_heap, (sim, counter, item))
                elif sim > top_heap[0][0]:
                    heapq.heapreplace(top_heap, (sim, counter, item))

        # 유사도 내림차순 정렬
        top_heap.sort(key=lambda x: x[0], reverse=True)
        return [entry[2] for entry in top_heap]
    finally:
        conn.close()


def get_vector_stats():
    """벡터 저장소 현황 통계 반환"""
    init_vector_db()
    conn = get_db_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM document_embeddings;").fetchone()[0]
        by_type = {}
        for r in conn.execute("SELECT doc_type, COUNT(*) as cnt FROM document_embeddings GROUP BY doc_type;"):
            by_type[r["doc_type"]] = r["cnt"]
        latest = conn.execute("SELECT MAX(updated_at) FROM document_embeddings;").fetchone()[0]
        return {
            "total_vectors": total,
            "by_type": by_type,
            "latest_update": latest or "없음",
            "db_path": VECTOR_DB_PATH
        }
    finally:
        conn.close()


def delete_vector_document(doc_id):
    """지정된 doc_id에 해당하는 벡터 임베딩 데이터를 삭제한다."""
    init_vector_db()
    with _db_lock:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM document_embeddings WHERE doc_id = ?;", (doc_id,))
            conn.commit()
        finally:
            conn.close()
