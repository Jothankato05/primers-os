import os
import importlib.util
from utils.logger import PrimersLogger

class PluginLoader:
    """
    Plugin system for auto-registering services.
    Scans services/ directory for plugins.
    """

    def __init__(self, shell):
        self.logger = PrimersLogger.get_logger("plugin_loader")
        self.shell = shell
        self.plugins = []

    def load_all(self):
        """Discover and load all plugins in the services/ directory."""
        services_dir = os.path.dirname(os.path.dirname(__file__))
        self.logger.info(f"Scanning for plugins in {services_dir}...")
        
        for item in os.listdir(services_dir):
            plugin_dir = os.path.join(services_dir, item)
            if os.path.isdir(plugin_dir):
                plugin_file = os.path.join(plugin_dir, "plugin.py")
                if os.path.exists(plugin_file):
                    self._load_plugin(plugin_file)

    def _load_plugin(self, file_path: str):
        try:
            module_name = f"services.{os.path.basename(os.path.dirname(file_path))}.plugin"
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                name = getattr(module, "NAME", "Unknown Plugin")
                desc = getattr(module, "DESCRIPTION", "")
                commands = getattr(module, "COMMANDS", {})
                register_fn = getattr(module, "register", None)
                
                if register_fn:
                    register_fn(self.shell)
                    self.plugins.append({"name": name, "desc": desc, "commands": commands})
                    self.logger.info(f"Loaded plugin: {name}")
                else:
                    self.logger.warning(f"Plugin {name} missing register() function.")
                    
        except Exception as e:
            self.logger.error(f"Failed to load plugin {file_path}: {e}")
