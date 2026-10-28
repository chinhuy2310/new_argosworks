import os
import time
import gzip
import shutil
import sqlite3
import json
import logging
import threading
import tarfile
import hashlib
from datetime import datetime
from config import DATA_DIR, BASE_DIR, CONFIG_PATH, ATTACH_DIR, load_config
import subprocess
from db import get_db_path, close_connection, init_db, ENGINE, DATABASE_URL

logger = logging.getLogger(__name__)

_backup_lock = threading.Lock()

def get_backup_dir():
    """현재 설정된 백업 디렉토리 경로를 반환 (절대 경로 보장)."""
    try:
        cfg = load_config()
        custom = (cfg.get("backup", {}).get("dir") or os.environ.get("BACKUP_DIR") or "").strip()
        if custom:
            if os.path.isabs(custom):
                return os.path.normpath(custom)
            return os.path.normpath(os.path.join(BASE_DIR, custom))
    except Exception:
        pass
    return os.path.normpath(os.path.join(DATA_DIR, "backups"))

def get_manifest_path():
    """현재 백업 디렉토리의 manifest.json 경로 반환."""
    return os.path.join(get_backup_dir(), "backups_manifest.json")

def _ensure_backup_dir():
    bdir = get_backup_dir()
    os.makedirs(bdir, exist_ok=True)
    return bdir

def _read_manifest():
    _ensure_backup_dir()
    manifest_path = get_manifest_path()
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _write_manifest(manifest):
    _ensure_backup_dir()
    manifest_path = get_manifest_path()
    tmp_path = manifest_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, manifest_path)

def _compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def update_backup_config(new_dir):
    """
    Admin이 백업 저장 경로를 변경할 때 유효성을 검사하고 config.json에 저장한다.
    new_dir가 빈 문자열("")이면 기본 경로(./data/backups)로 복원된다.
    """
    new_dir = (new_dir or "").strip()
    if new_dir:
        resolved_path = new_dir if os.path.isabs(new_dir) else os.path.normpath(os.path.join(BASE_DIR, new_dir))
        try:
            os.makedirs(resolved_path, exist_ok=True)
            test_file = os.path.join(resolved_path, f".write_test_{int(time.time())}")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("test")
            if os.path.exists(test_file):
                os.remove(test_file)
        except Exception as e:
            raise ValueError(f"지정한 경로에 백업을 생성할 수 없습니다 (권한 부족 또는 잘못된 경로: {e})")
    
    # Save to config.json
    try:
        raw_cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw_cfg = json.load(f)
        raw_cfg.setdefault("backup", {})["dir"] = new_dir
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(raw_cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"설정 저장 실패: {e}")

    active_dir = get_backup_dir()
    default_dir = os.path.normpath(os.path.join(DATA_DIR, "backups"))
    return {
        "ok": True,
        "backup_dir": active_dir,
        "default_dir": default_dir,
        "is_custom": (active_dir != default_dir)
    }

def import_backup_file(file_bytes, original_filename, note="외부 업로드 백업"):
    """
    사용자가 로컬 PC/외부 드라이브에서 업로드한 백업 파일(.tar.gz, .db.gz 또는 .db)을 검증하고 
    현재 백업 디렉토리에 정식 백업본으로 안전하게 등록한다.
    """
    with _backup_lock:
        bdir = _ensure_backup_dir()
        safe_name = os.path.basename(original_filename).replace(" ", "_")
        
        is_tar = safe_name.endswith(".tar.gz")
        is_gz = safe_name.endswith(".db.gz")
        is_raw_db = safe_name.endswith(".db")

        if not (is_tar or is_gz or is_raw_db):
            raise ValueError("지원하지 않는 백업 파일 형식입니다. (.tar.gz, .db.gz 또는 .db 파일만 가능합니다)")

        if is_raw_db:
            final_name = safe_name + ".gz"
        else:
            final_name = safe_name

        dest_path = os.path.join(bdir, final_name)
        if os.path.exists(dest_path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_name = f"imported_{ts}_{final_name}"
            dest_path = os.path.join(bdir, final_name)

        # 1. 파일 저장
        if is_raw_db:
            with gzip.open(dest_path, "wb", compresslevel=6) as f_out:
                f_out.write(file_bytes)
        else:
            with open(dest_path, "wb") as f_out:
                f_out.write(file_bytes)

        # 2. SQLite 무결성 검사
        chk_tmp = os.path.join(bdir, f"chk_import_{datetime.now().strftime('%H%M%S')}.tmp.db")
        try:
            if is_tar:
                with tarfile.open(dest_path, "r:gz") as tar:
                    db_member = None
                    for m in tar.getmembers():
                        if m.name.endswith(".db") or m.name.endswith(".sqlite"):
                            db_member = m
                            break
                    if not db_member:
                        raise RuntimeError("백업 아카이브(.tar.gz) 내에 유효한 SQLite 데이터베이스가 없습니다.")
                    with open(chk_tmp, "wb") as f_out:
                        extracted = tar.extractfile(db_member)
                        shutil.copyfileobj(extracted, f_out)
            else:
                with gzip.open(dest_path, "rb") as f_in, open(chk_tmp, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            conn = sqlite3.connect(chk_tmp)
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            res = cur.fetchone()
            conn.close()
            if not res or res[0] != "ok":
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                raise RuntimeError(f"가져온 백업 파일의 CSDL 무결성 검증 실패: {res}")
        finally:
            if os.path.exists(chk_tmp):
                try:
                    os.remove(chk_tmp)
                except Exception:
                    pass

        # 3. Manifest 등록
        now = datetime.now()
        manifest = _read_manifest()
        manifest[final_name] = {
            "filename": final_name,
            "created_at": now.isoformat(),
            "type": "imported",
            "note": note,
            "gz_size": os.path.getsize(dest_path),
            "format": "tar.gz" if is_tar else "db.gz"
        }
        _write_manifest(manifest)

        return {
            "ok": True,
            "filename": final_name,
            "gz_size": os.path.getsize(dest_path),
            "note": note
        }

def create_backup(note="수동 백업", backup_type="manual"):
    """
    Enterprise Full Backup:
    1. SQLite Online Backup API를 사용하여 zero-corruption WAL 스냅샷 생성
    2. PRAGMA integrity_check 무결성 검증 및 SHA-256 해시 계산
    3. 첨부파일 디렉토리(attachments) 및 CSDL을 tar.gz로 완전 패키징
    """
    with _backup_lock:
        bdir = _ensure_backup_dir()
        now = datetime.now()
        ts_str = now.strftime("%Y%m%d_%H%M%S")
        base_name = f"argos_backup_{ts_str}_{backup_type}"
        temp_meta_path = os.path.join(bdir, f"{base_name}.meta.json")
        final_tar_name = f"{base_name}.tar.gz"
        final_tar_path = os.path.join(bdir, final_tar_name)

        is_postgres = (ENGINE == "postgres")
        if is_postgres:
            temp_db_path = os.path.join(bdir, f"{base_name}.dump")
        else:
            temp_db_path = os.path.join(bdir, f"{base_name}.tmp.db")
            src_path = get_db_path()
            if not os.path.exists(src_path):
                raise FileNotFoundError(f"데이터베이스 파일이 존재하지 않습니다: {src_path}")

        try:
            if is_postgres:
                # 1. PostgreSQL Enterprise Backup via pg_dump -Fc (Custom compressed format)
                cmd = [_find_pg_tool("pg_dump"), "-Fc", "-d", DATABASE_URL, "-f", temp_db_path]
                try:
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                except FileNotFoundError:
                    raise FileNotFoundError(
                        "PostgreSQL 클라이언트 도구(pg_dump)가 시스템에 설치되어 있지 않습니다. "
                        "Dockerfile 또는 호스트에 postgresql-client 패키지를 설치해주세요."
                    )
                if res.returncode != 0:
                    raise RuntimeError(f"PostgreSQL pg_dump 백업 실패 (code {res.returncode}): {res.stderr}")

                raw_db_size = os.path.getsize(temp_db_path)
                db_sha256 = _compute_sha256(temp_db_path)
            else:
                # 1. SQLite Online Backup API (WAL 모드에서도 일관성 100% 보장)
                src_conn = sqlite3.connect(src_path)
                dest_conn = sqlite3.connect(temp_db_path)
                with dest_conn:
                    src_conn.backup(dest_conn)
                dest_conn.close()
                src_conn.close()

                # 2. 백업 파일 SQLite 무결성 검증 (Integrity Check)
                check_conn = sqlite3.connect(temp_db_path)
                cur = check_conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                res = cur.fetchone()
                check_conn.close()
                if not res or res[0] != "ok":
                    raise RuntimeError(f"백업 데이터 무결성 검사 실패: {res}")

                raw_db_size = os.path.getsize(temp_db_path)
                db_sha256 = _compute_sha256(temp_db_path)

            # 3. 내부 메타데이터 JSON 생성
            attach_count = 0
            if os.path.exists(ATTACH_DIR):
                for root, _, files in os.walk(ATTACH_DIR):
                    attach_count += len(files)

            meta_data = {
                "version": "2.0",
                "app": "ARGOS WORKS",
                "created_at": now.isoformat(),
                "type": backup_type,
                "note": note,
                "db_sha256": db_sha256,
                "db_raw_size": raw_db_size,
                "attachments_count": attach_count
            }
            with open(temp_meta_path, "w", encoding="utf-8") as mf:
                json.dump(meta_data, mf, ensure_ascii=False, indent=2)

            # 4. Tar.gz 아카이브 생성 (DB + Attachments + Manifest)
            with tarfile.open(final_tar_path, "w:gz", compresslevel=6) as tar:
                # Add database (argos.dump for Postgres, argos.db for SQLite)
                arcname_db = "argos.dump" if is_postgres else "argos.db"
                tar.add(temp_db_path, arcname=arcname_db)
                # Add metadata manifest
                tar.add(temp_meta_path, arcname="backup_manifest.json")
                # Add attachments directory if exists
                if os.path.exists(ATTACH_DIR):
                    tar.add(ATTACH_DIR, arcname="attachments")

            tar_size = os.path.getsize(final_tar_path)

            # 5. Manifest 메타데이터 등록
            manifest = _read_manifest()
            manifest[final_tar_name] = {
                "filename": final_tar_name,
                "created_at": now.isoformat(),
                "type": backup_type,
                "note": note,
                "raw_size": raw_db_size,
                "gz_size": tar_size,
                "format": "tar.gz",
                "sha256": db_sha256,
                "attachments_count": attach_count
            }
            _write_manifest(manifest)

            # 6. 보관 주기 관리: 자동 백업(auto)은 최근 14일 / 30건 유지
            if backup_type == "auto":
                _prune_old_backups(manifest, max_days=14, max_count=30)

            logger.info(f"[Backup] 풀 아카이브 백업 완료: {final_tar_name} (DB {raw_db_size}B + 첨부파일 {attach_count}건 -> 압축 {tar_size}B)")
            return {
                "ok": True,
                "filename": final_tar_name,
                "created_at": now.isoformat(),
                "raw_size": raw_db_size,
                "gz_size": tar_size,
                "type": backup_type,
                "note": note,
                "sha256": db_sha256,
                "attachments_count": attach_count
            }
        finally:
            for p in (temp_db_path, temp_meta_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

MAX_BACKUP_EXTRACT_SIZE = 1024 * 1024 * 1024  # 1GB total limit
MAX_BACKUP_FILE_COUNT = 10000

def _safe_extract_tar(tar, target_dir):
    """Extract tar archive safely protecting against path traversal, symlinks, and tar bombs."""
    target_dir_abs = os.path.abspath(target_dir)
    total_size = 0
    file_count = 0

    for member in tar.getmembers():
        file_count += 1
        if file_count > MAX_BACKUP_FILE_COUNT:
            raise RuntimeError("백업 아카이브에 포함된 파일 개수가 제한(10,000개)을 초과했습니다.")

        # Check file types: reject symlinks, hardlinks, device nodes
        if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
            raise RuntimeError(f"백업 아카이브에 허용되지 않는 특수 파일이 포함되어 있습니다: {member.name}")

        # Check path traversal: reject absolute paths and relative traversals
        clean_name = os.path.normpath(member.name)
        if os.path.isabs(clean_name) or clean_name.startswith("..") or "/../" in member.name or "\\..\\" in member.name:
            raise RuntimeError(f"백업 아카이브에 비정상적인 파일 경로가 포함되어 있습니다: {member.name}")

        dest_path = os.path.abspath(os.path.join(target_dir_abs, clean_name))
        if not (dest_path == target_dir_abs or dest_path.startswith(target_dir_abs + os.sep)):
            raise RuntimeError(f"경로 이탈(Path Traversal) 공격이 감지되었습니다: {member.name}")

        total_size += member.size
        if total_size > MAX_BACKUP_EXTRACT_SIZE:
            raise RuntimeError("백업 아카이브의 총 압축 해제 용량이 제한(1GB)을 초과했습니다.")

    # Python 3.12+ data filter or member extraction
    if hasattr(tarfile, 'data_filter'):
        tar.extractall(target_dir, filter='data')
    else:
        for member in tar.getmembers():
            tar.extract(member, target_dir)

def restore_backup(backup_filename):
    """
    지정한 백업 파일(.tar.gz 또는 .db.gz)로부터 CSDL 및 첨부파일을 1-Click 복원한다.
    복원 전 현재 상태를 안전 스냅샷으로 자동 저장하여 실수로 복원하더라도 100% 원복 가능하도록 보호한다.
    """
    with _backup_lock:
        bdir = _ensure_backup_dir()
        safe_filename = os.path.basename(backup_filename)
        archive_path = os.path.join(bdir, safe_filename)

        is_tar = safe_filename.endswith(".tar.gz")
        is_gz = safe_filename.endswith(".db.gz")
        if not os.path.exists(archive_path) or not (is_tar or is_gz):
            raise FileNotFoundError(f"유효한 백업 파일을 찾을 수 없습니다: {safe_filename}")

        is_postgres = (ENGINE == "postgres")
        src_db_path = get_db_path()
        temp_restore_db = os.path.join(bdir, "argos_restore_temp.dump" if is_postgres else "argos_restore_temp.db")
        temp_extract_dir = os.path.join(bdir, f"extract_temp_{int(time.time())}")

        # 1. 안전 사전 백업 생성 (Pre-restore Safety Backup)
        safety_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_name = f"argos_safety_before_restore_{safety_ts}"
        safety_path = os.path.join(bdir, f"{safety_name}.tar.gz")
        try:
            if is_postgres:
                safety_tmp = os.path.join(bdir, f"{safety_name}.dump")
                try:
                    res = subprocess.run([_find_pg_tool("pg_dump"), "-Fc", "-d", DATABASE_URL, "-f", safety_tmp], capture_output=True)
                    if res.returncode == 0:
                        with tarfile.open(safety_path, "w:gz", compresslevel=6) as star:
                            star.add(safety_tmp, arcname="argos.dump")
                            if os.path.exists(ATTACH_DIR):
                                star.add(ATTACH_DIR, arcname="attachments")
                except FileNotFoundError:
                    logger.warning("pg_dump를 찾을 수 없어 사전 안전 백업 생성을 건너뜁니다.")
                if os.path.exists(safety_tmp):
                    os.remove(safety_tmp)
            elif os.path.exists(src_db_path):
                safety_tmp_db = os.path.join(bdir, f"{safety_name}.tmp.db")
                s_conn = sqlite3.connect(src_db_path)
                d_conn = sqlite3.connect(safety_tmp_db)
                with d_conn:
                    s_conn.backup(d_conn)
                d_conn.close()
                s_conn.close()

                with tarfile.open(safety_path, "w:gz", compresslevel=6) as star:
                    star.add(safety_tmp_db, arcname="argos.db")
                    if os.path.exists(ATTACH_DIR):
                        star.add(ATTACH_DIR, arcname="attachments")

                if os.path.exists(safety_tmp_db):
                    os.remove(safety_tmp_db)
        except Exception as se:
            logger.warning(f"안전 백업 생성 중 경고: {se}")

        try:
            # 2. 압축 해제 및 DB 파일 준비
            has_attachments = False
            if is_tar:
                os.makedirs(temp_extract_dir, exist_ok=True)
                with tarfile.open(archive_path, "r:gz") as tar:
                    _safe_extract_tar(tar, temp_extract_dir)

                extracted_db = None
                # Search for postgres dump or sqlite db
                for root, _, files in os.walk(temp_extract_dir):
                    for f in files:
                        if is_postgres and (f.endswith(".dump") or f == "argos.dump"):
                            extracted_db = os.path.join(root, f)
                            break
                        elif not is_postgres and (f.endswith(".db") or f.endswith(".sqlite")):
                            extracted_db = os.path.join(root, f)
                            break
                    if extracted_db:
                        break

                if not extracted_db:
                    db_type_expected = "PostgreSQL dump (.dump)" if is_postgres else "SQLite (.db/.sqlite)"
                    raise RuntimeError(f"백업 아카이브 내에 유효한 {db_type_expected} 데이터베이스가 없습니다.")

                shutil.copyfile(extracted_db, temp_restore_db)

                extracted_attach = os.path.join(temp_extract_dir, "attachments")
                if os.path.exists(extracted_attach) and os.path.isdir(extracted_attach):
                    has_attachments = True
            else:
                with gzip.open(archive_path, "rb") as f_in, open(temp_restore_db, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # 3. 복원 대상 무결성 검증 및 복원 실행
            close_connection(force=True)

            if is_postgres:
                # PostgreSQL pg_restore execution with clean drop/create
                cmd = [_find_pg_tool("pg_restore"), "--clean", "--if-exists", "-d", DATABASE_URL, temp_restore_db]
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True)
                except FileNotFoundError:
                    raise FileNotFoundError(
                        "PostgreSQL 복원 도구(pg_restore)가 시스템에 설치되어 있지 않습니다. "
                        "Dockerfile 또는 호스트에 postgresql-client 패키지를 설치해주세요."
                    )
                # pg_restore may return 1 on warnings (e.g. notices), returncode > 1 is failure
                if res.returncode > 1:
                    raise RuntimeError(f"PostgreSQL pg_restore 복원 실패 (code {res.returncode}): {res.stderr}")
            else:
                # SQLite integrity check & restore
                check_conn = sqlite3.connect(temp_restore_db)
                cur = check_conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                res = cur.fetchone()
                check_conn.close()
                if not res or res[0] != "ok":
                    raise RuntimeError(f"복원할 백업 파일의 무결성이 손상되었습니다: {res}")

                # SQLite Online Backup API hot restore
                restore_conn = sqlite3.connect(temp_restore_db)
                live_conn = sqlite3.connect(src_db_path)
                with live_conn:
                    restore_conn.backup(live_conn)
                restore_conn.close()
                live_conn.close()

            # 6. 첨부파일 디렉토리 복원 (있을 경우)
            if has_attachments and os.path.exists(temp_extract_dir):
                extracted_attach = os.path.join(temp_extract_dir, "attachments")
                if os.path.exists(extracted_attach):
                    os.makedirs(ATTACH_DIR, exist_ok=True)
                    for item in os.listdir(extracted_attach):
                        s = os.path.join(extracted_attach, item)
                        d = os.path.join(ATTACH_DIR, item)
                        if os.path.isdir(s):
                            if os.path.exists(d):
                                shutil.rmtree(d, ignore_errors=True)
                            shutil.copytree(s, d)
                        else:
                            shutil.copy2(s, d)

            # 7. 최신 스키마 마이그레이션 재확인/적용
            init_db()

            logger.info(f"[Backup] 복원 성공: {safe_filename} (첨부파일 동기화: {has_attachments})")
            return {
                "ok": True,
                "restored_file": safe_filename,
                "safety_backup": os.path.basename(safety_path),
                "attachments_restored": has_attachments
            }
        finally:
            if os.path.exists(temp_restore_db):
                try:
                    os.remove(temp_restore_db)
                except Exception:
                    pass
            if os.path.exists(temp_extract_dir):
                try:
                    shutil.rmtree(temp_extract_dir, ignore_errors=True)
                except Exception:
                    pass

def list_backups():
    """사용 가능한 백업 목록을 최신순으로 정렬하여 반환한다."""
    bdir = _ensure_backup_dir()
    manifest = _read_manifest()
    results = []

    for fname in os.listdir(bdir):
        if not (fname.endswith(".tar.gz") or fname.endswith(".db.gz")):
            continue
        fpath = os.path.join(bdir, fname)
        info = manifest.get(fname, {})
        stat = os.stat(fpath)
        created_at = info.get("created_at") or datetime.fromtimestamp(stat.st_mtime).isoformat()
        b_type = info.get("type") or ("auto" if "_auto" in fname else ("safety" if "safety" in fname else ("imported" if "import" in fname else "manual")))
        note = info.get("note") or ("자동 정기 백업" if b_type == "auto" else ("복원 전 안전 스냅샷" if b_type == "safety" else ("외부 업로드 백업" if b_type == "imported" else "수동 백업")))
        gz_size = stat.st_size
        fmt = "tar.gz" if fname.endswith(".tar.gz") else "db.gz"

        results.append({
            "filename": fname,
            "created_at": created_at,
            "type": b_type,
            "note": note,
            "gz_size": gz_size,
            "raw_size": info.get("raw_size", gz_size * 3),
            "format": fmt,
            "sha256": info.get("sha256", ""),
            "attachments_count": info.get("attachments_count", 0)
        })

    # 최신 날짜순 정렬
    results.sort(key=lambda x: x["created_at"], reverse=True)
    return results

def get_backup_file_path(filename):
    """안전하게 백업 파일 절대 경로를 검증하여 반환 (디렉토리 탈출 방어)."""
    bdir = _ensure_backup_dir()
    safe_name = os.path.basename(filename)
    target = os.path.join(bdir, safe_name)
    if os.path.exists(target) and (safe_name.endswith(".tar.gz") or safe_name.endswith(".db.gz")):
        return target
    return None

def _prune_old_backups(manifest, max_days=14, max_count=30):
    """보관 기간이 지난 자동 백업 파일 정리"""
    bdir = _ensure_backup_dir()
    now = datetime.now()
    auto_backups = []
    for fname in os.listdir(bdir):
        if (fname.endswith(".tar.gz") or fname.endswith(".db.gz")) and ("_auto" in fname or manifest.get(fname, {}).get("type") == "auto"):
            fpath = os.path.join(bdir, fname)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            auto_backups.append((fname, fpath, mtime))

    auto_backups.sort(key=lambda x: x[2], reverse=True)

    # 1. 수량 초과분 삭제
    to_delete = auto_backups[max_count:]
    # 2. 일수 초과분 삭제
    for item in auto_backups[:max_count]:
        age_days = (now - item[2]).total_seconds() / 86400.0
        if age_days > max_days:
            to_delete.append(item)

    for fname, fpath, _ in to_delete:
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
            if fname in manifest:
                del manifest[fname]
            logger.info(f"[Backup] 만료된 자동 백업 제거: {fname}")
        except Exception as e:
            logger.warning(f"오래된 백업 삭제 실패 ({fname}): {e}")

    _write_manifest(manifest)

def start_backup_scheduler(interval_hours=24):
    """
    백그라운드에서 주기적으로 데이터베이스 및 첨부파일을 자동 백업하는 데몬 스레드.
    서버 구동 후 매 시간 체크하며, 마지막 자동 백업 후 interval_hours가 경과했으면 새 백업을 수행한다.
    """
    def _loop():
        time.sleep(30)  # 서버 기동 직후 안정화 대기
        while True:
            try:
                manifest = _read_manifest()
                now = datetime.now()
                last_auto_time = None
                for item in manifest.values():
                    if item.get("type") == "auto":
                        try:
                            dt = datetime.fromisoformat(item["created_at"])
                            if not last_auto_time or dt > last_auto_time:
                                last_auto_time = dt
                        except Exception:
                            pass

                need_backup = False
                if not last_auto_time:
                    need_backup = True
                else:
                    elapsed = (now - last_auto_time).total_seconds() / 3600.0
                    if elapsed >= interval_hours:
                        need_backup = True

                if need_backup:
                    logger.info("[Backup Scheduler] 정기 자동 풀 아카이브 백업을 시작합니다...")
                    create_backup(note="스케줄러 자동 정기 백업", backup_type="auto")
            except Exception as e:
                logger.error(f"[Backup Scheduler] 자동 백업 오류: {e}")

            time.sleep(3600)  # 1시간마다 확인

    t = threading.Thread(target=_loop, daemon=True, name="ArgosBackupScheduler")
    t.start()
    logger.info(f"[Backup Scheduler] 백업 스케줄러 시작됨 (주기: {interval_hours}시간)")
