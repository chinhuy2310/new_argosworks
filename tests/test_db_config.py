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
