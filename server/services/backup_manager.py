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

def _find_pg_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        os.path.join(BASE_DIR, 'pgsql', 'bin'),
        os.path.join(BASE_DIR, 'vendor', 'pgsql', 'bin'),
        os.path.join(os.path.dirname(BASE_DIR), 'pgsql', 'bin'),
        os.path.join(os.path.dirname(BASE_DIR), 'vendor', 'pgsql', 'bin'),
    ]
    for cdir in candidates:
        candidate_exe = os.path.join(cdir, f'{name}.exe' if os.name == 'nt' else name)
        if os.path.isfile(candidate_exe):
            return candidate_exe
    return name


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
    # Only the admin-configured value is returned; the resolved default path and
    # any absolute server layout stay server-side (F-0006).
    return {
        "ok": True,
        "backup_dir": active_dir,
        "is_custom": (active_dir != default_dir)
    }

def import_backup_file(file_bytes, original_filename, note="외부 업로드 백업"):
    """
    Validate and register a user-uploaded SQLite or PostgreSQL backup archive.
    PostgreSQL archives are checked with pg_restore --list; they are never
    silently interpreted as SQLite files.
    """
    with _backup_lock:
        bdir = _ensure_backup_dir()
        safe_name = os.path.basename(original_filename).replace(" ", "_")

        is_tar = safe_name.endswith(".tar.gz")
        is_gz = safe_name.endswith(".db.gz")
        is_raw_db = safe_name.endswith(".db")
        if not (is_tar or is_gz or is_raw_db):
            raise ValueError("지원하지 않는 백업 파일 형식입니다. (.tar.gz, .db.gz 또는 .db 파일만 가능합니다)")

        final_name = safe_name + ".gz" if is_raw_db else safe_name
        dest_path = os.path.join(bdir, final_name)
        if os.path.exists(dest_path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_name = f"imported_{ts}_{final_name}"
            dest_path = os.path.join(bdir, final_name)

        if is_raw_db:
            with gzip.open(dest_path, "wb", compresslevel=6) as output_file:
                output_file.write(file_bytes)
        else:
            with open(dest_path, "wb") as output_file:
                output_file.write(file_bytes)

        check_suffix = ".dump" if ENGINE == "postgres" else ".tmp.db"
        chk_tmp = os.path.join(bdir, f"chk_import_{datetime.now().strftime('%H%M%S_%f')}{check_suffix}")
        try:
            detected_engine = "sqlite"
            if is_tar:
                with tarfile.open(dest_path, "r:gz") as archive:
                    members = [m for m in archive.getmembers() if m.isfile()]
                    dump_members = [m for m in members if os.path.basename(m.name) == "argos.dump" or m.name.endswith(".dump")]
                    sqlite_members = [m for m in members if m.name.lower().endswith((".db", ".sqlite"))]
                    if dump_members and sqlite_members:
                        raise RuntimeError("백업 아카이브에 PostgreSQL과 SQLite 데이터베이스가 함께 포함되어 있습니다.")
                    if dump_members:
                        db_member = dump_members[0]
                        detected_engine = "postgres"
                    elif sqlite_members:
                        db_member = sqlite_members[0]
                        detected_engine = "sqlite"
                    else:
                        raise RuntimeError("백업 아카이브에 검증 가능한 데이터베이스 파일이 없습니다.")

                    manifest_member = next(
                        (m for m in members if os.path.basename(m.name) == "backup_manifest.json"),
                        None
                    )
                    if manifest_member:
                        manifest_file = archive.extractfile(manifest_member)
                        if manifest_file:
                            try:
                                embedded_manifest = json.loads(manifest_file.read().decode("utf-8"))
                                declared_engine = embedded_manifest.get("database_engine")
                                if declared_engine and declared_engine != detected_engine:
                                    raise RuntimeError("백업 Manifest의 DB 엔진 정보가 실제 파일과 일치하지 않습니다.")
                            except json.JSONDecodeError as manifest_error:
                                raise RuntimeError("백업 Manifest JSON이 손상되었습니다.") from manifest_error

                    extracted = archive.extractfile(db_member)
                    if extracted is None:
                        raise RuntimeError("백업 데이터베이스 파일을 읽을 수 없습니다.")
                    with open(chk_tmp, "wb") as output_file:
                        shutil.copyfileobj(extracted, output_file)
            else:
                with gzip.open(dest_path, "rb") as source_file, open(chk_tmp, "wb") as output_file:
                    shutil.copyfileobj(source_file, output_file)

            if detected_engine != ENGINE:
                raise ValueError(
                    f"백업 DB 엔진({detected_engine})이 현재 서버 엔진({ENGINE})과 다릅니다. "
                    "동일한 DB 엔진의 서버에서 가져오세요."
                )

            if detected_engine == "postgres":
                try:
                    verify = subprocess.run(
                        [_find_pg_tool("pg_restore"), "--list", chk_tmp],
                        capture_output=True,
                        text=True
                    )
                except FileNotFoundError as tool_error:
                    raise FileNotFoundError(
                        "PostgreSQL 백업 검증 도구(pg_restore)가 없습니다. postgresql-client 패키지를 설치해주세요."
                    ) from tool_error
                if verify.returncode != 0:
                    raise RuntimeError(f"가져온 PostgreSQL 백업 검증 실패: {verify.stderr}")
            else:
                conn = sqlite3.connect(chk_tmp)
                try:
                    result = conn.execute("PRAGMA integrity_check;").fetchone()
                    if not result or result[0] != "ok":
                        raise RuntimeError(f"가져온 SQLite 백업 무결성 검증 실패: {result}")
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'records', 'schema_migrations');")
                    tables = {row[0] for row in cur.fetchall()}
                    if not tables.intersection({'users', 'records', 'schema_migrations'}):
                        raise RuntimeError("가져온 백업 파일에 ARGOS WORKS 필수 테이블이 존재하지 않습니다 (빈 데이터베이스).")
                finally:
                    conn.close()

        except Exception:
            try:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
            except OSError:
                pass
            raise
        finally:
            try:
                if os.path.exists(chk_tmp):
                    os.remove(chk_tmp)
            except OSError:
                pass

        now = datetime.now()
        manifest = _read_manifest()
        manifest[final_name] = {
            "filename": final_name,
            "created_at": now.isoformat(),
            "type": "imported",
            "note": note,
            "gz_size": os.path.getsize(dest_path),
            "format": "tar.gz" if is_tar else "db.gz",
            "database_engine": ENGINE
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
                "database_engine": "postgres" if is_postgres else "sqlite",
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

def _rollback_restore_from_safety_snapshot(safety_path, is_postgres, src_db_path, rollback_dir):
    """Restore the verified pre-restore snapshot after any post-write restore failure."""
    os.makedirs(rollback_dir, exist_ok=True)
    with tarfile.open(safety_path, "r:gz") as safety_tar:
        _safe_extract_tar(safety_tar, rollback_dir)

    db_name = "argos.dump" if is_postgres else "argos.db"
    safety_db = None
    for root, _, files in os.walk(rollback_dir):
        if db_name in files:
            safety_db = os.path.join(root, db_name)
            break
    if not safety_db:
        raise RuntimeError("안전 스냅샷에서 원본 데이터베이스 파일을 찾을 수 없습니다.")

    close_connection(force=True)
    if is_postgres:
        cmd = [
            _find_pg_tool("pg_restore"), "--clean", "--if-exists",
            "--exit-on-error", "--single-transaction", "-d", DATABASE_URL, safety_db
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"PostgreSQL 안전 스냅샷 롤백 실패: {result.stderr}")
    else:
        check_conn = sqlite3.connect(safety_db)
        try:
            check = check_conn.execute("PRAGMA integrity_check;").fetchone()
        finally:
            check_conn.close()
        if not check or check[0] != "ok":
            raise RuntimeError(f"안전 스냅샷 SQLite 무결성 검사 실패: {check}")
        source_conn = sqlite3.connect(safety_db)
        live_conn = sqlite3.connect(src_db_path)
        try:
            with live_conn:
                source_conn.backup(live_conn)
        finally:
            source_conn.close()
            live_conn.close()

    # Restore attachments as a directory snapshot, not as an overlay.
    snapshot_attachments = os.path.join(rollback_dir, "attachments")
    if os.path.isdir(snapshot_attachments):
        if os.path.exists(ATTACH_DIR):
            shutil.rmtree(ATTACH_DIR)
        shutil.copytree(snapshot_attachments, ATTACH_DIR)
    elif os.path.exists(ATTACH_DIR):
        shutil.rmtree(ATTACH_DIR)


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

        # 1. Create and verify a safety snapshot before any destructive restore.
        safety_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_name = f"argos_safety_before_restore_{safety_ts}"
        safety_path = os.path.join(bdir, f"{safety_name}.tar.gz")
        safety_tmp = os.path.join(
            bdir, f"{safety_name}.dump" if is_postgres else f"{safety_name}.tmp.db"
        )
        try:
            if is_postgres:
                dump_cmd = [
                    _find_pg_tool("pg_dump"), "-Fc", "-d", DATABASE_URL, "-f", safety_tmp
                ]
                dump_res = subprocess.run(dump_cmd, capture_output=True, text=True)
                if dump_res.returncode != 0 or not os.path.isfile(safety_tmp) or os.path.getsize(safety_tmp) == 0:
                    err_msg = dump_res.stderr if dump_res.returncode != 0 else "덤프 파일이 생성되지 않았거나 크기가 0바이트입니다."
                    raise RuntimeError(
                        f"복원 전 PostgreSQL 안전 백업 생성 실패 (code {dump_res.returncode}): {err_msg}"
                    )
                verify_cmd = [_find_pg_tool("pg_restore"), "--list", safety_tmp]
                verify_res = subprocess.run(verify_cmd, capture_output=True, text=True)
                if verify_res.returncode != 0:
                    raise RuntimeError(
                        f"복원 전 PostgreSQL 안전 백업 검증 실패: {verify_res.stderr}"
                    )
                with tarfile.open(safety_path, "w:gz", compresslevel=6) as star:
                    star.add(safety_tmp, arcname="argos.dump")
                    if os.path.exists(ATTACH_DIR):
                        star.add(ATTACH_DIR, arcname="attachments")
            else:
                if not os.path.isfile(src_db_path):
                    raise RuntimeError("복원 전 SQLite 안전 백업을 만들 원본 DB 파일이 없습니다.")
                source_conn = sqlite3.connect(src_db_path)
                snapshot_conn = sqlite3.connect(safety_tmp)
                try:
                    with snapshot_conn:
                        source_conn.backup(snapshot_conn)
                    check = snapshot_conn.execute("PRAGMA integrity_check;").fetchone()
                    if not check or check[0] != "ok":
                        raise RuntimeError(f"복원 전 SQLite 안전 백업 무결성 검사 실패: {check}")
                finally:
                    snapshot_conn.close()
                    source_conn.close()
                with tarfile.open(safety_path, "w:gz", compresslevel=6) as star:
                    star.add(safety_tmp, arcname="argos.db")
                    if os.path.exists(ATTACH_DIR):
                        star.add(ATTACH_DIR, arcname="attachments")

            if not os.path.isfile(safety_path) or os.path.getsize(safety_path) == 0:
                raise RuntimeError("복원 전 안전 백업 아카이브가 생성되지 않았습니다.")
            with tarfile.open(safety_path, "r:gz") as check_tar:
                names = check_tar.getnames()
                expected_member = "argos.dump" if is_postgres else "argos.db"
                if expected_member not in names:
                    raise RuntimeError("복원 전 안전 백업에 데이터베이스 파일이 포함되지 않았습니다.")
        except Exception as safety_error:
            try:
                if os.path.exists(safety_path):
                    os.remove(safety_path)
            except OSError:
                pass
            if isinstance(safety_error, FileNotFoundError):
                raise FileNotFoundError(
                    "PostgreSQL 안전 백업 검증 도구(pg_restore)가 시스템에 설치되어 있지 않습니다. "
                    "Dockerfile 또는 호스트에 postgresql-client 패키지를 설치해주세요."
                ) from safety_error
            raise RuntimeError(
                f"안전 스냅샷을 검증하지 못해 데이터 복원을 중단했습니다: {safety_error}"
            ) from safety_error
        finally:
            try:
                if os.path.exists(safety_tmp):
                    os.remove(safety_tmp)
            except OSError:
                pass

        restore_started = False
        rollback_dir = os.path.join(bdir, f"rollback_temp_{int(time.time() * 1000000)}")
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
                cmd = [
                    _find_pg_tool("pg_restore"), "--clean", "--if-exists",
                    "--exit-on-error", "--single-transaction", "-d", DATABASE_URL, temp_restore_db
                ]
                restore_started = True
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True)
                except FileNotFoundError:
                    raise FileNotFoundError(
                        "PostgreSQL 복원 도구(pg_restore)가 시스템에 설치되어 있지 않습니다. "
                        "Dockerfile 또는 호스트에 postgresql-client 패키지를 설치해주세요."
                    )
                # pg_restore returns non-zero when restore errors occurred; never report
                # a potentially partial restore as successful.
                if res.returncode != 0:
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
                restore_started = True
                restore_conn = sqlite3.connect(temp_restore_db)
                live_conn = sqlite3.connect(src_db_path)
                with live_conn:
                    restore_conn.backup(live_conn)
                restore_conn.close()
                live_conn.close()

            # 6. Replace attachments only when the archive actually contains
            # an attachment snapshot. Legacy .db.gz backups are database-only;
            # they must not erase the live attachment directory.
            extracted_attach = os.path.join(temp_extract_dir, "attachments") if is_tar else None
            if extracted_attach and os.path.isdir(extracted_attach):
                if os.path.exists(ATTACH_DIR):
                    shutil.rmtree(ATTACH_DIR)
                shutil.copytree(extracted_attach, ATTACH_DIR)
                has_attachments = True

            # 7. 최신 스키마 마이그레이션 재확인/적용
            init_db()

            logger.info(f"[Backup] 복원 성공: {safe_filename} (첨부파일 동기화: {has_attachments})")
            return {
                "ok": True,
                "restored_file": safe_filename,
                "safety_backup": os.path.basename(safety_path),
                "attachments_restored": has_attachments
            }
        except Exception as restore_error:
            if restore_started:
                try:
                    _rollback_restore_from_safety_snapshot(
                        safety_path, is_postgres, src_db_path, rollback_dir
                    )
                except Exception as rollback_error:
                    raise RuntimeError(
                        f"복원 작업 실패: {restore_error}. 사전 안전 스냅샷 롤백도 실패했습니다: {rollback_error}. "
                        f"안전 백업 파일을 보존했습니다: {os.path.basename(safety_path)}"
                    ) from restore_error
                raise RuntimeError(
                    f"복원 작업이 실패하여 사전 안전 스냅샷으로 원상 복구했습니다: {restore_error}"
                ) from restore_error
            raise
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
            if os.path.exists(rollback_dir):
                try:
                    shutil.rmtree(rollback_dir, ignore_errors=True)
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
