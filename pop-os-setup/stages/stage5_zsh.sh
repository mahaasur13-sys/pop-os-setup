#!/bin/bash
#===============================================================================
# Stage 5 — Zsh + Oh My Zsh
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_zsh() {
    step "ZSH + OH MY ZSH" "5"

    local user="${CURRENT_USER:-$(get_current_user)}"
    local home="${HOMEDIR:-$(get_home_dir "$user")}"

    if [[ ! -d "$home/.oh-my-zsh" ]]; then
        log "Installing Oh My Zsh for $user..."
        export RUNZSH=no
        sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
    else
        ok "Oh My Zsh already installed"
    fi

    # Plugins
    local zsh_custom="$home/.oh-my-zsh/custom"
    mkdir -p "$zsh_custom/plugins"

    if [[ ! -d "$zsh_custom/plugins/zsh-autosuggestions" ]]; then
        git clone -q https://github.com/zsh-users/zsh-autosuggestions.git \
            "$zsh_custom/plugins/zsh-autosuggestions"
    fi

    if [[ ! -d "$zsh_custom/plugins/zsh-syntax-highlighting" ]]; then
        git clone -q https://github.com/zsh-users/zsh-syntax-highlighting.git \
            "$zsh_custom/plugins/zsh-syntax-highlighting"
    fi

    ok "Zsh plugins installed"

    # Set default shell
    local current_shell
    current_shell=$(basename "$SHELL")
    if [[ "$current_shell" != "zsh" ]]; then
        chsh -s /bin/zsh "$user" 2>/dev/null || true
        ok "Zsh set as default shell for $user"
    else
        ok "Zsh already default shell"
    fi
}