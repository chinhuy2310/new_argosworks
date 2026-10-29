import pytest
import services.jira_client as jc
from services.jira_client import check_jira_ssl_warning

def test_jira_ssl_default_strict_no_warning(monkeypatch, capsys):
    """Verify default Jira client does not output insecure SSL warning."""
    monkeypatch.delenv("JIRA_INSECURE_SKIP_VERIFY", raising=False)
    jc._WARNED_JIRA_SSL = False

    check_jira_ssl_warning({"jira": {"enabled": True}})
    captured = capsys.readouterr()
    assert "[SECURITY WARNING] Jira SSL certificate verification is disabled" not in captured.err


def test_jira_ssl_warning_when_env_enabled(monkeypatch, capsys):
    """Verify warning is logged when JIRA_INSECURE_SKIP_VERIFY=true."""
    monkeypatch.setenv("JIRA_INSECURE_SKIP_VERIFY", "true")
    jc._WARNED_JIRA_SSL = False

    check_jira_ssl_warning()
    captured = capsys.readouterr()
    assert "[SECURITY WARNING] Jira SSL certificate verification is disabled (insecure_skip_verify). DO NOT USE IN PRODUCTION." in captured.err


def test_jira_ssl_warning_when_config_enabled(monkeypatch, capsys):
    """Verify warning is logged when config.json has jira.insecure_skip_verify: true."""
    monkeypatch.delenv("JIRA_INSECURE_SKIP_VERIFY", raising=False)
    jc._WARNED_JIRA_SSL = False

    check_jira_ssl_warning({"jira": {"insecure_skip_verify": True}})
    captured = capsys.readouterr()
    assert "[SECURITY WARNING] Jira SSL certificate verification is disabled (insecure_skip_verify). DO NOT USE IN PRODUCTION." in captured.err
