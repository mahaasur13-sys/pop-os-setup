#!/bin/bash
#===============================================================================
# Stage 22 — Neovim + LSP + AI Coding Assistant Setup
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_neovim() {
    step "NEOVIM + LSP + AI CODING" "22"

    log "Configuring Neovim + LSP..."

    # Neovim
    if ! command -v nvim &>/dev/null; then
        log "Installing Neovim..."
        sudo apt install -y neovim 2>/dev/null || \
        curl -LO https://github.com/neovim/neovim/releases/latest/download/nvim-linux64.tar.gz && \
        sudo tar -xzf nvim-linux64.tar.gz -C /opt && \
        sudo ln -sf /opt/nvim-linux64/bin/nvim /usr/local/bin/nvim && \
        rm -f nvim-linux64.tar.gz
    fi

    # LunarVim orNvChad (lightweight AI-ready config)
    local nvim_dir="${HOME}/.config/nvim"
    if [[ ! -d "$nvim_dir" ]]; then
        log "Setting upNvChad (Neovim config framework)..."
        git clone -b v2.0 https://github.com/NvChad/NvChad "$nvim_dir" 2>/dev/null || true
    fi

    # Language servers
    mkdir -p "${HOME}/.local/share/nvim/lsp_servers"
    log "LSP servers will be installed on first use"

    ok "Neovim configured — run nvim to start"
}

stage22_neovim() { stage_neovim; }