"""
Sample PRIMERS OS plugin - copy this file to
~/.local/share/primers/plugins/ to start writing your own.
"""

NAME = "Sample Hello Plugin"
DESCRIPTION = "Adds a simple hello command to the OS."
COMMANDS = {
    "hello": "Say hello from the plugin system",
}


def plugin_hello(cmd=None, shell=None):
    who = " ".join(cmd.args) if cmd is not None and cmd.args else "world"
    return f"Hello, {who}! - from the PRIMERS OS plugin system ⚛"


def register(shell):
    """Called once at boot with the running shell."""
    shell.register_command("hello", plugin_hello, COMMANDS["hello"])
