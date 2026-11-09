#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync / Import all products from https://vision119.com/ as sample data.
Saves to data/vision119_products.json, downloads product images/attachments,
and stores products in SQLite database (argos.db) and vector index.
"""

import sys
import os
import re
import json
import time
import argparse
from datetime import datetime
from urllib.parse import urljoin, urlparse

# Reconfigure stdout/stderr for UTF-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure server package can be imported
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import requests
from bs4 import BeautifulSoup

from services.data_store import write_products, query, execute
from utils.logging import log_line

BASE_URL = "https://vision119.com"

CATEGORY_NAMES = {
    1: '카메라',
    2: 'LED 안내판',
    3: '비상벨 시스템',
    4: '녹화기',
    5: '주변장치',
    6: 'POLE',
    7: '음식물 처리기',
    8: '보안등 및 조명등',
    9: '비상벨 안내판',
    10: '스마트 솔루션',
    13: '솔루션'
}

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    return session

def get_category_product_ids(session, cate_id):
    page = 1
    items = []
    while True:
        url = f"{BASE_URL}/ko/sub/04.product/sub04_01.php?cateId={cate_id}&cPage={page}"
        try:
            r = session.get(url, timeout=15)
            r.encoding = r.apparent_encoding
            page_items = list(dict.fromkeys(re.findall(r"onclickBbs\('(\d+)','view'\)", r.text)))
            if not page_items:
                break
            new_items = [x for x in page_items if x not in items]
            if not new_items:
                break
            items.extend(new_items)
            next_pages = [int(p) for p in re.findall(r"jsViewPage\('(\d+)'\)", r.text) if int(p) > page]
            if not next_pages:
                break
            page += 1
        except Exception as e:
            print(f"[!] Error fetching cate {cate_id} page {page}: {e}")
            break
    return items

def parse_table_smart(table):
    specs = {}
    matrix = None
    if not table:
        return specs, matrix

    rows = table.find_all('tr')
    if not rows:
        return specs, matrix

    thead = table.find('thead')
    header_tr = thead.find('tr') if thead else rows[0]
    headers = [clean_text(th.get_text()) for th in header_tr.find_all(['th', 'td'])]

    # Case 1: Multi-column variant table (e.g. Category 8 lighting: 제품명, LED출력, 규격, 재질, 물품번호)
    is_variant_matrix = any(h in ['제품명', '물품번호', '식별번호', 'LED출력', '규격명·규격', '규격', '모델명', '모델'] for h in headers) and len(headers) >= 3

    if is_variant_matrix:
        clean_headers = []
        for i, h in enumerate(headers):
            if '이미지' not in h and '사진' not in h and h:
                clean_headers.append((i, h))

        data_trs = table.find('tbody').find_all('tr') if table.find('tbody') else rows[1:]
        variant_rows = []
        for tr in data_trs:
            tds = tr.find_all(['td', 'th'])
            if not tds:
                continue
            cells = [clean_text(td.get_text()) for td in tds]
            if all(c in headers for c in cells if c):
                continue
            row_dict = {}
            for col_idx, hname in clean_headers:
                if col_idx < len(cells):
                    row_dict[hname] = cells[col_idx]
            if row_dict and any(row_dict.values()):
                variant_rows.append(row_dict)

        for v in variant_rows:
            sub_model = v.get('제품명') or v.get('규격명·규격') or v.get('모델') or f"모델-{len(specs)+1}"
            details = []
            for col_idx, hname in clean_headers:
                if hname not in ['제품명', '규격명·규격', '모델']:
                    val = v.get(hname)
                    if val:
                        details.append(f"{hname}: {val}")
            spec_key = f"세부 모델 > {sub_model}"
            specs[spec_key] = " | ".join(details) if details else "기본 규격"

        matrix = {"headers": [h for _, h in clean_headers], "rows": variant_rows}
        return specs, matrix

    # Case 2: Model comparison table (e.g. Category 2 smart LED display: Row 0 has multiple model names)
    first_cells = [clean_text(td.get_text()) for td in rows[0].find_all(['td', 'th'])]
    if len(first_cells) >= 3 and any(w in first_cells[0] for w in ['모델', '양면', '단면']):
        model_names = [m for m in first_cells[1:] if m]
        attr_rows = []
        for tr in rows[1:]:
            cells = [clean_text(td.get_text()) for td in tr.find_all(['td', 'th'])]
            if len(cells) >= 2:
                attr_name = cells[0]
                attr_vals = cells[1:]
                attr_rows.append((attr_name, attr_vals))

        if model_names and attr_rows:
            for idx, mname in enumerate(model_names):
                m_details = []
                for aname, avals in attr_rows:
                    if idx < len(avals) and avals[idx]:
                        m_details.append(f"{aname}: {avals[idx]}")
                    elif len(avals) == 1 and avals[0]:
                        m_details.append(f"{aname}: {avals[0]}")
                specs[f"모델 라인업 > {mname}"] = " | ".join(m_details) if m_details else "표준 사양"

            for aname, avals in attr_rows:
                if len(avals) == 1:
                    specs[f"공통 사양 > {aname}"] = avals[0]
            return specs, None

    # Case 3: Standard hierarchical or flat key-value specs
    current_group = ""
    for tr in rows:
        tds = tr.find_all(['td', 'th'])
        if not tds:
            continue
        texts = [clean_text(td.get_text()) for td in tds]
        if len(texts) == 2 and texts[0] == '모델':
            specs["기본 사양 > 모델"] = texts[1]
            continue
        elif len(texts) == 3 and texts[1] == '모델':
            specs["기본 사양 > 모델"] = texts[2]
            continue

        # Ignore header rows or image-only columns accidentally reaching case 3
        if any(h in ['식별번호', '규격명·규격', '제품 이미지'] for h in texts):
            continue
        if len(tds) == 3:
            group = texts[0]
            if group: current_group = group
            key, val = texts[1], texts[2]
            if key and val and '이미지' not in val and '사진' not in val:
                full_key = f"{current_group} > {key}" if current_group else key
                specs[full_key] = val
        elif len(tds) == 2:
            key, val = texts[0], texts[1]
            if key and val:
                full_key = f"{current_group} > {key}" if current_group else key
                specs[full_key] = val
        elif len(tds) >= 4:
            key = texts[0]
            val = " | ".join(texts[1:])
            if key and val:
                full_key = f"{current_group} > {key}" if current_group else key
                specs[full_key] = val

    return specs, None

def parse_product_detail(session, cate_id, bbs_id):
    url = f"{BASE_URL}/ko/sub/04.product/sub04_01.php?cateId={cate_id}&method=view&bbsId={bbs_id}"
    try:
        r = session.get(url, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        print(f"[!] Error fetching product {cate_id}/{bbs_id}: {e}")
        return None

    view = soup.find('div', class_='product_view')
    if not view:
        return None

    pd_ttl = view.find('div', class_='pd_ttl')
    model = pd_ttl.get_text(strip=True) if pd_ttl else ""

    pd_eng = view.find('div', class_='pd_eng')
    display_name = pd_eng.get_text(strip=True) if pd_eng else ""

    pd_exp = view.find('div', class_='pd_exp')
    exp_text = pd_exp.get_text(strip=True) if pd_exp else ""

    # Procurement ID
    procurement_no = None
    all_text = view.get_text()
    m_proc = re.search(r'식별번호\s*[:：]?\s*(\d{7,10})', all_text)
    if m_proc:
        procurement_no = m_proc.group(1)

    # Bullet points / Summary
    bullets = []
    pd_eng2 = view.find('div', class_=re.compile(r'pd_eng2'))
    if pd_eng2:
        for line in pd_eng2.stripped_strings:
            clean = line.strip()
            if clean.startswith('-') or clean.startswith('■') or clean.startswith('▶') or clean.startswith('•'):
                bullets.append(clean.lstrip('- ■▶•').strip())
            elif clean and not clean.startswith('---') and '펌웨어' not in clean and '버전정보' not in clean and '해시정보' not in clean:
                bullets.append(clean)

    summary = "\n".join(bullets)

    # Fallbacks for model and display_name
    if not model:
        if display_name:
            model = display_name
        else:
            ttl_li = soup.find('li', class_='ttl')
            model = ttl_li.get_text(strip=True) if ttl_li else f"VISION-{bbs_id}"

    if not display_name or display_name == model:
        if exp_text and '식별번호' not in exp_text:
            display_name = f"{model} ({exp_text})"
        else:
            display_name = model

    # Image URL
    img_elem = view.find('div', class_='view_hd_L')
    img_url = ""
    if img_elem:
        img_tag = img_elem.find('img')
        if img_tag and img_tag.get('src'):
            img_url = urljoin(BASE_URL, img_tag['src'])

    # Catalog PDF link
    catalog_url = ""
    for a in view.find_all('a', href=True):
        href = a['href']
        if 'download.php' in href or href.endswith('.pdf'):
            catalog_url = urljoin(BASE_URL, href)
            break

    # Smart specs parsing
    table = view.find('table', class_='tg') or view.find('table')
    specs, matrix = parse_table_smart(table)

    category = CATEGORY_NAMES.get(cate_id, '기타')
    now_iso = datetime.now().isoformat()

    return {
        "id": f"P-V119-{bbs_id}",
        "bbsId": str(bbs_id),
        "cateId": str(cate_id),
        "model": model,
        "displayName": display_name,
        "family": category,
        "category": category,
        "lifecycle": "판매 중",
        "summary": summary,
        "memo": f"vision119.com 자동 동기화 ({url})",
        "specs": specs,
        "specMatrix": matrix,
        "procurement": {
            "registeredName": model,
            "identificationNo": procurement_no,
            "price": None,
            "configuration": ""
        } if procurement_no else None,
        "price": 0,
        "currency": "KRW",
        "source": "vision119",
        "sourceUrl": url,
        "imageUrl": img_url,
        "catalogUrl": catalog_url,
        "revision": 1,
        "createdAt": now_iso,
        "updatedAt": now_iso
    }

def download_product_media(session, products, attach_root):
    os.makedirs(attach_root, exist_ok=True)
    downloaded_cnt = 0
    for p in products:
        pid = p["id"]
        p_dir = os.path.join(attach_root, pid)
        os.makedirs(p_dir, exist_ok=True)
        attachments = []

        existing_files = os.listdir(p_dir)
        photo_file = next((f for f in existing_files if '_photo' in f or f.endswith(('.png', '.jpg', '.jpeg', '.webp'))), None)

        if not photo_file and p.get("imageUrl"):
            img_url = p["imageUrl"]
            ext = os.path.splitext(urlparse(img_url).path)[1] or '.png'
            safe_model = re.sub(r'[^\w\-]', '_', p['model'])
            photo_file = f"{safe_model}_photo{ext}"
            photo_path = os.path.join(p_dir, photo_file)
            try:
                r = session.get(img_url, timeout=12)
                if r.status_code == 200:
                    with open(photo_path, 'wb') as fp:
                        fp.write(r.content)
                    downloaded_cnt += 1
                else:
                    photo_file = None
            except Exception:
                photo_file = None

        if photo_file:
            photo_path = os.path.join(p_dir, photo_file)
            if os.path.exists(photo_path):
                attachments.append({
                    "name": photo_file,
                    "size": os.path.getsize(photo_path),
                    "uploadedAt": p["updatedAt"]
                })

        # Catalog PDF
        pdf_file = next((f for f in existing_files if f.endswith('.pdf')), None)
        if not pdf_file and p.get("catalogUrl"):
            cat_url = p["catalogUrl"]
            safe_model = re.sub(r'[^\w\-]', '_', p['model'])
            pdf_file = f"{safe_model}_catalog.pdf"
            pdf_path = os.path.join(p_dir, pdf_file)
            try:
                r = session.get(cat_url, timeout=15)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(pdf_path, 'wb') as fp:
                        fp.write(r.content)
                    downloaded_cnt += 1
                else:
                    pdf_file = None
            except Exception:
                pdf_file = None

        if pdf_file:
            pdf_path = os.path.join(p_dir, pdf_file)
            if os.path.exists(pdf_path):
                attachments.append({
                    "name": pdf_file,
                    "size": os.path.getsize(pdf_path),
                    "uploadedAt": p["updatedAt"]
                })

        p["attachments"] = attachments
    return downloaded_cnt

def sync_to_database(products):
    now_iso = datetime.now().isoformat()
    cat_rows = query("SELECT id, name FROM product_categories")
    existing_cats = {r["name"] for r in cat_rows}

    for cid, cname in CATEGORY_NAMES.items():
        if cname not in existing_cats:
            cat_id = f"cat-v119-{cid}"
            execute("INSERT INTO product_categories (id, name, spec_template, created_at) VALUES (?, ?, ?, ?)",
                    (cat_id, cname, "[]", now_iso))
            existing_cats.add(cname)

    write_products(products, target_source="vision119")
    print(f"[OK] Successfully wrote {len(products)} products with source='vision119' to database.")

def main():
    parser = argparse.ArgumentParser(description="Sync products from vision119.com as sample data")
    parser.add_argument("--file", type=str, default="", help="Load products from existing JSON file instead of live crawling")
    parser.add_argument("--no-media", action="store_true", help="Skip downloading media attachments")
    parser.add_argument("--sync-vector", action="store_true", help="Trigger vector store sync after db insert")
    args = parser.parse_args()

    data_dir = os.path.join(BASE_DIR, "data")
    json_path = os.path.join(data_dir, "vision119_products.json")
    sync_state_path = os.path.join(data_dir, "vision119_sync_state.json")
    attach_root = os.path.join(data_dir, "attachments", "products")

    session = get_session()
    products = []

    if args.file and os.path.exists(args.file):
        print(f"[*] Loading products from file: {args.file}")
        with open(args.file, "r", encoding="utf-8") as f:
            products = json.load(f)
    else:
        print("[*] Starting live crawl from https://vision119.com ...")
        t0 = time.time()
        seen_ids = set()
        for cid, cname in CATEGORY_NAMES.items():
            ids = get_category_product_ids(session, cid)
            print(f"  Category [{cid}] {cname}: {len(ids)} items found")
            for bid in ids:
                if bid in seen_ids:
                    continue
                seen_ids.add(bid)
                p = parse_product_detail(session, cid, bid)
                if p:
                    products.append(p)
        print(f"[*] Crawled {len(products)} products in {time.time()-t0:.2f}s")

    if not products:
        print("[!] No products found or loaded. Aborting.")
        return 1

    # Media download
    if not args.no_media:
        print("[*] Downloading media attachments (photos & catalog PDFs)...")
        downloaded = download_product_media(session, products, attach_root)
        print(f"[*] Media sync complete. Newly downloaded: {downloaded}")

    # Save to JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"[OK] Saved products dataset to {json_path}")

    # Update sync state
    sync_state = {
        "lastSyncedAt": datetime.now().isoformat(),
        "totalSynced": len(products)
    }
    with open(sync_state_path, "w", encoding="utf-8") as f:
        json.dump(sync_state, f, ensure_ascii=False, indent=2)
    print(f"[OK] Updated sync state: {sync_state_path} ({len(products)} products)")

    # Save to database
    sync_to_database(products)

    # Optional vector sync
    if args.sync_vector:
        try:
            from services.vector_store import trigger_async_vector_sync
            from config import load_config
            cfg = load_config()
            print("[*] Triggering background vector store re-indexing for AI search / RAG...")
            trigger_async_vector_sync(cfg)
            print("[OK] Vector store sync triggered in background.")
        except Exception as e:
            print(f"[!] Vector sync notice: {e}")

    print("\n========================================================")
    print(f"[OK] Vision119 sample products sync complete! Total: {len(products)} products.")
    print("========================================================")
    return 0

if __name__ == "__main__":
    sys.exit(main())
