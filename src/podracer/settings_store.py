"""The app's QSettings store: one fixed user-level file.

QSettings("PodRacer", "PodRacer") with the native format is per-OS
and unredirectable on macOS (CFPreferences plist), which let the test
suite and headless probes write the user's real settings (seen
2026-09-20: the suite's fs/home sentinel landed in
~/Library/Preferences). The app therefore constructs its store by
explicit file path: XDG_CONFIG_HOME or ~/.config per PodRacer.conf —
the exact file the Linux native format already used, so Linux keeps
its store untouched, macOS migrates over once, and tests redirect via
XDG_CONFIG_HOME on every platform. The store is independent of where
the app (or its bundle) lives.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

ORG = "PodRacer"
APP = "PodRacer"

_configured = False


def settings_file() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if not xdg:
        xdg = str(Path.home() / ".config")
    return Path(xdg) / ORG / f"{APP}.conf"


def app_settings() -> QSettings:
    """The app's store, migrated from the macOS plist if needed."""
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    store = QSettings(str(path), QSettings.Format.IniFormat)
    _migrate_from_native(store)
    return store


def _migrate_from_native(store: QSettings) -> None:
    """Carry the macOS CFPreferences store over, once.

    The plist held the real settings until 2026-09-20 and also the
    test suite's dead fs/home sentinels: every value except fs/home
    migrates, so a stale saved folder cannot resurrect itself. No-op
    when the file store already has values.
    """
    if store.allKeys():
        return
    native = QSettings(QSettings.Format.NativeFormat,
                       QSettings.Scope.UserScope, ORG, APP)
    for key in native.allKeys():
        if key == "fs/home":
            continue
        value = native.value(key)
        if value not in (None, "", [], {}):
            store.setValue(key, value)
    if store.allKeys():
        store.sync()
