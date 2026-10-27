# -*- coding: utf-8 -*-
"""test_config_jira_env.py — Jira settings must be settable from .env/environment.

Regression: `load_config()` copied JIRA_API_TOKEN/EMAIL/BASE_URL/PROJECT_KEY from the
environment but never read JIRA_ENABLED or JIRA_PROJECT_MAP, so a .env with
JIRA_ENABLED=true still produced `jira.enabled = False` and every Jira call
silently no-op'd (no sync, no create, no error message).
"""
import os
import sys

import pytest

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import config as server_config  # noqa: E402

JIRA_ENV_KEYS = (
    "JIRA_ENABLED",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_PROJECT_KEY",
    "JIRA_PROJECT_MAP",
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Keep load_config() away from the real server/config.json and the real .env."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server_config, "CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(server_config, "_load_env", lambda: None)
    for key in JIRA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestJiraEnabledEnv:
    def test_truthy_values_enable_jira(self, isolated_config):
        isolated_config.setenv("JIRA_ENABLED", "true")
        assert server_config.load_config()["jira"]["enabled"] is True

    @pytest.mark.parametrize("value", ["1", "yes", "on", "TRUE", " True "])
    def test_all_truthy_spellings(self, isolated_config, value):
        isolated_config.setenv("JIRA_ENABLED", value)
        assert server_config.load_config()["jira"]["enabled"] is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
    def test_falsy_values_keep_jira_disabled(self, isolated_config, value):
        isolated_config.setenv("JIRA_ENABLED", value)
        assert server_config.load_config()["jira"]["enabled"] is False

    def test_unset_env_keeps_jira_disabled(self, isolated_config):
        assert server_config.load_config()["jira"]["enabled"] is False


class TestJiraConnectionEnv:
    def test_credentials_and_project_key_are_taken_from_env(self, isolated_config):
        isolated_config.setenv("JIRA_ENABLED", "true")
        isolated_config.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
        isolated_config.setenv("JIRA_EMAIL", "user@example.com")
        isolated_config.setenv("JIRA_API_TOKEN", "plain-token")
        isolated_config.setenv("JIRA_PROJECT_KEY", "SCRUM")

        jira = server_config.load_config()["jira"]

        assert jira["enabled"] is True
        assert jira["base_url"] == "https://example.atlassian.net"
        assert jira["email"] == "user@example.com"
        assert jira["api_token"] == "plain-token"
        assert jira["default_project_key"] == "SCRUM"


class TestJiraProjectMapEnv:
    def test_json_object_is_parsed(self, isolated_config):
        isolated_config.setenv(
            "JIRA_PROJECT_MAP", '{"dev": {"project_key": "SCRUM", "issue_type": "Task"}}'
        )
        jira = server_config.load_config()["jira"]
        assert jira["project_map"] == {"dev": {"project_key": "SCRUM", "issue_type": "Task"}}

    def test_empty_value_keeps_default_map(self, isolated_config):
        isolated_config.setenv("JIRA_PROJECT_MAP", "{}")
        assert server_config.load_config()["jira"]["project_map"] == {}

    @pytest.mark.parametrize("broken", ["{not json", '["dev"]', "42"])
    def test_invalid_json_is_ignored(self, isolated_config, broken):
        isolated_config.setenv("JIRA_PROJECT_MAP", broken)
        assert server_config.load_config()["jira"]["project_map"] == {}
