import pytest
from db import _detect_engine

@pytest.mark.parametrize("url,expected_engine", [
    ("", "sqlite"),
    ("   ", "sqlite"),
    (None, "sqlite"),
    ("postgres://user:super_secret_pw@db.internal:5432/argos", "postgres"),
    ("postgresql://user:super_secret_pw@db.internal:5432/argos", "postgres"),
    ("postgresql+psycopg2://user:super_secret_pw@db.internal:5432/argos", "postgres"),
    ("sqlite:///data/argos.db", "sqlite"),
])
def test_detect_engine_supported(url, expected_engine):
    assert _detect_engine(url) == expected_engine


def test_detect_engine_unsupported_fails_closed_without_leaking_credentials():
    secret_pw = "super_secret_mysql_password_123"
    unsupported_url = f"mysql://dbadmin:{secret_pw}@mysql.internal:3306/argos_prod"

    with pytest.raises(RuntimeError) as exc_info:
        _detect_engine(unsupported_url)

    err_msg = str(exc_info.value)
    assert "Unsupported DATABASE_URL scheme: mysql" in err_msg
    # Ensure credentials are NOT leaked in exception message
    assert secret_pw not in err_msg
    assert "dbadmin" not in err_msg


def test_dead_regex_removed():
    import db
    assert not hasattr(db, "_RE_INSERT_OR_REPLACE"), "_RE_INSERT_OR_REPLACE dead regex should be removed"


def test_all_insert_or_replace_tables_mapped():
    """Verify that every table with an INSERT OR REPLACE in server/ codebase is mapped in _REPLACE_PK_MAP."""
    import os
    import re
    from db import _REPLACE_PK_MAP

    server_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
    pattern = re.compile(r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)", re.IGNORECASE)
    
    found_tables = set()
    for root, _, files in os.walk(server_dir):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as py_file:
                    content = py_file.read()
                    matches = pattern.findall(content)
                    for m in matches:
                        found_tables.add(m.lower())

    for tbl in found_tables:
        assert tbl in _REPLACE_PK_MAP, f"Table '{tbl}' uses INSERT OR REPLACE but is missing from db._REPLACE_PK_MAP"


def test_multi_row_insert_or_replace_translation():
    """Verify _translate_sql produces correct ON CONFLICT clause at the end for multi-row inserts."""
    from db import _translate_sql
    
    sql = "INSERT OR REPLACE INTO card_sequences (dept_id, last_seq) VALUES (?, ?), (?, ?)"
    translated = _translate_sql(sql)
    
    assert "INSERT INTO card_sequences" in translated
    assert translated.count("ON CONFLICT") == 1
    assert translated.endswith("ON CONFLICT (dept_id) DO UPDATE SET last_seq = EXCLUDED.last_seq")
    assert "%s, %s" in translated

