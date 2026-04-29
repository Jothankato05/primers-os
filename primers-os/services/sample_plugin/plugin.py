NAME = "Sample Hello Plugin"
DESCRIPTION = "Adds a simple hello command to the OS."
COMMANDS = {
    "hello": "Say hello from the plugin system"
}

def register(shell):
    """
    Registers plugin commands with the shell.
    In a real system, the shell might have a register_command method.
    We'll assume the shell's command_interpreter.COMMAND_MAP can be updated.
    """
    # Add to interpreter's command map
    shell.command_interpreter.COMMAND_MAP["hello"] = ("plugin_hello", "Hello from plugin")
    
    # Add a custom handler to the shell if needed
    # For now, we'll just let the shell's dispatch handle it via action name
    pass

def plugin_hello():
    return "Hello from the PRIMERS OS Plugin System! ⚛"
