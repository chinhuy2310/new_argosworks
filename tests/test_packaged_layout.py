# -*- coding: utf-8 -*-
"""Tests for the packaged (Nuitka/.exe) layout helpers: app_paths and master-key bootstrap."""
import importlib
import os
import sys

import pytest

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _reload_app_paths(monkeypatch, frozen, argv0=None, home=None):
    for name in ("ARGOS_HOME",):
        monkeypatch.delenv(name, raising=False)
    if home:
        monkeypatch.setenv("ARGOS_HOME", home)
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    if argv0:
        monkeypatch.setattr(sys, "argv", [argv0])
    import app_paths
    return importlib.reload(app_paths)


def test_source_layout_is_repo_root(monkeypatch):
    mod = _reload_app_paths(monkeypatch, frozen=False)
    assert not mod.IS_FROZEN
    assert mod.APP_HOME == os.path.dirname(SERVER_DIR)
    assert mod.WEB_ROOT == mod.APP_HOME
    assert mod.RES_DIR == SERVER_DIR
    importlib.reload(mod)


def test_frozen_layout_uses_executable_folder(monkeypatch, tmp_path):
    exe = tmp_path / "ArgosWorks.exe"
    mod = _reload_app_paths(monkeypatch, frozen=True, argv0=str(exe))
    assert mod.IS_FROZEN
    assert mod.APP_HOME == str(tmp_path)
    # Read-only resources come from the bundle (module folder), not from the exe folder.
    assert mod.WEB_ROOT == mod.RES_DIR


def test_argos_home_override(monkeypatch, tmp_path):
    mod = _reload_app_paths(monkeypatch, frozen=True, argv0="/somewhere/ArgosWorks", home=str(tmp_path))
    assert mod.APP_HOME == str(tmp_path)


@pytest.fixture
def crypto_module(monkeypatch, tmp_path):
    import utils.crypto as crypto
    monkeypatch.delenv("ARGOS_MASTER_KEY", raising=False)
    monkeypatch.delenv("JARVIS_MASTER_KEY", raising=False)
    monkeypatch.setattr(crypto, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setattr(crypto, "_CACHED_MASTER_KEY", None)
    yield crypto
    crypto._CACHED_MASTER_KEY = None


def test_missing_key_still_fatal_outside_packaged_build(crypto_module, monkeypatch):
    monkeypatch.setattr(crypto_module, "IS_FROZEN", False)
    with pytest.raises(RuntimeError):
        crypto_module.get_master_key()
    assert not os.path.exists(crypto_module.ENV_PATH)


def test_packaged_build_generates_and_persists_key(crypto_module, monkeypatch):
    monkeypatch.setattr(crypto_module, "IS_FROZEN", True)
    first = crypto_module.get_master_key()
    assert len(first) == 32
    with open(crypto_module.ENV_PATH, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.startswith("ARGOS_MASTER_KEY=")]
    assert len(lines) == 1 and len(lines[0].split("=", 1)[1]) == 64

    # A later start (fresh process state) must reuse the same key, not generate another.
    monkeypatch.setattr(crypto_module, "_CACHED_MASTER_KEY", None)
    assert crypto_module.get_master_key() == first
    with open(crypto_module.ENV_PATH, encoding="utf-8") as fh:
        assert fh.read().count("ARGOS_MASTER_KEY=") == 1


def test_packaged_build_preserves_existing_env_content(crypto_module, monkeypatch):
    monkeypatch.setattr(crypto_module, "IS_FROZEN", True)
    with open(crypto_module.ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write("PORT=9090")  # no trailing newline on purpose
    crypto_module.get_master_key()
    with open(crypto_module.ENV_PATH, encoding="utf-8") as fh:
        content = fh.read()
    assert content.startswith("PORT=9090\n")
    assert "ARGOS_MASTER_KEY=" in content
