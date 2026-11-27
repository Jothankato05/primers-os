"""
PRIMERS OS - Plugin loader.

Plugins are Python files exposing ``NAME``, ``DESCRIPTION``, ``COMMANDS``
and a ``register(shell)`` function that calls
``shell.register_command(word, handler, description)``.

Searched locations:
  * ``services/<name>/plugin.py`` inside the PRIMERS install
  * ``~/.local/share/primers/plugins/*.py`` (or ``$PRIMERS_DATA_DIR/plugins``)

User plugins run with the user's own permissions. Files that other users
could have modified (group/world-writable, or not owned by the user) are
skipped.
"""

import importlib.util
import os
import stat
from typing import List

from utils import paths
from utils.logger import PrimersLogger


class PluginLoader:
    def __init__(self, shell):
        self.logger = PrimersLogger.get_logger("plugin_loader")
        self.shell = shell
        self.plugins: List[dict] = []

    def load_all(self) -> List[dict]:
        services_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for item in sorted(os.listdir(services_dir)):
            plugin_file = os.path.join(services_dir, item, "plugin.py")
            if os.path.isfile(plugin_file):
                self._load_plugin(plugin_file, f"services.{item}.plugin")

        user_dir = paths.user_plugin_dir()
        if os.path.isdir(user_dir):
            for item in sorted(os.listdir(user_dir)):
                path = os.path.join(user_dir, item)
                if item.endswith(".py") and os.path.isfile(path):
                    if self._is_trusted(path):
                        self._load_plugin(path, f"primers_user_plugins.{item[:-3]}")
                    else:
                        self.logger.warning(f"Skipping untrusted plugin (permissions/owner): {path}")
        return self.plugins

    @staticmethod
    def _is_trusted(path: str) -> bool:
        try:
            st = os.stat(path)
            dir_st = os.stat(os.path.dirname(path))
        except OSError:
            return False
        uid = os.getuid() if hasattr(os, "getuid") else st.st_uid
        for s in (st, dir_st):
            if s.st_uid != uid or s.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return False
        return True

    def _load_plugin(self, file_path: str, module_name: str):
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                return
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            name = getattr(module, "NAME", os.path.basename(os.path.dirname(file_path)))
            register_fn = getattr(module, "register", None)
            if not callable(register_fn):
                self.logger.warning(f"Plugin {name} has no register() function - skipped.")
                return
            register_fn(self.shell)
            self.plugins.append({
                "name": name,
                "desc": getattr(module, "DESCRIPTION", ""),
                "commands": getattr(module, "COMMANDS", {}),
                "path": file_path,
            })
            self.logger.info(f"Loaded plugin: {name}")
        except Exception as e:  # a broken plugin must not stop the OS booting
            self.logger.error(f"Failed to load plugin {file_path}: {e}")
