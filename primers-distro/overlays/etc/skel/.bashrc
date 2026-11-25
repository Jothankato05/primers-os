# PRIMERS OS — default bash configuration
[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc
case $- in *i*) ;; *) return ;; esac

HISTCONTROL=ignoreboth
HISTSIZE=5000
shopt -s histappend checkwinsize
[ -f /usr/share/bash-completion/bash_completion ] && . /usr/share/bash-completion/bash_completion

export PS1='\[\033[96m\]⚛ \u\[\033[90m\]@\[\033[96m\]\h\[\033[0m\]:\[\033[94m\]\w\[\033[0m\]\$ '
export PATH="$HOME/.local/bin:$PATH"

alias ls='ls --color=auto'
alias ll='ls -alF'
alias la='ls -A'
alias grep='grep --color=auto'
alias install-module='primers-install'
alias run-windows='primers-compat'

if [ -z "${PRIMERS_QUIET:-}" ] && [ "$SHLVL" -le 2 ]; then
  echo ""
  echo "  ⚛  PRIMERS OS 1.0 Genesis"
  echo "  'primers' — AI brain   ·   'primers-install' — add software"
  echo ""
fi
