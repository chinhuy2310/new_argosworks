# -*- coding: utf-8 -*-
import os
import sys
import json
import pytest

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from handlers.settings_handler import _serialize_env_value, _write_env_updates


def test_serialize_env_value_dict():
    val = {"lab": {"project_key": "VS", "issue_type": ""}}
    serialized = _serialize_env_value(val)
    assert serialized == '{"lab": {"project_key": "VS", "issue_type": ""}}'
    # Must be valid json with double quotes
    parsed = json.loads(serialized)
    assert parsed == val


def test_serialize_env_value_single_quoted_string():
    val = "{'lab': {'project_key': 'VS'}}"
    serialized = _serialize_env_value(val)
    assert serialized == '{"lab": {"project_key": "VS"}}'
    assert json.loads(serialized) == {"lab": {"project_key": "VS"}}


def test_serialize_env_value_plain_string():
    assert _serialize_env_value("simple_value") == "simple_value"
    assert _serialize_env_value(123) == "123"


def test_write_env_updates_dict_preserves_valid_json(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("JIRA_PROJECT_MAP={}\n", encoding="utf-8")
    monkeypatch.setattr("handlers.settings_handler.ENV_PATH", str(env_file))

    _write_env_updates({"JIRA_PROJECT_MAP": {"lab": {"project_key": "VS"}}})

    content = env_file.read_text(encoding="utf-8")
    assert 'JIRA_PROJECT_MAP={"lab": {"project_key": "VS"}}' in content
