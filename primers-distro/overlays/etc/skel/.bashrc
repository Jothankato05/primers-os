# PRIMERS OS — Default shell config
export PS1='\[\033[96m\]⚛ primers\[\033[90m\]@\[\033[96m\]\h\[\033[0m\]:\[\033[94m\]\w\[\033[0m\]\$ '
export PATH="$HOME/.local/bin:$PATH"
alias ll='ls -alF'
alias la='ls -A'
alias primers='python3 /usr/share/primers/brain/main.py'
alias install-module='primers-install'
alias run-windows='primers-compat'
echo ""
echo "  ⚛  PRIMERS OS 1.0 Genesis"
echo "  Type 'primers' to launch the AI brain"
echo "  Type 'primers-install' to add software modules"
echo ""
