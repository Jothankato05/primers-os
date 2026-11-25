# PRIMERS OS — login shell profile
[ -n "$BASH_VERSION" ] && [ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"
[ -d "$HOME/.local/bin" ] && PATH="$HOME/.local/bin:$PATH"
