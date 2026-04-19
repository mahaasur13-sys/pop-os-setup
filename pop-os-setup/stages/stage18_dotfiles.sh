#!/bin/bash
#===============================================================================
# Stage 18 — Custom .dotfiles / Shell Config Backup & Link
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_dotfiles() {
    step "DOTFILES + SHELL CONFIG" "18"

    local dotfiles_dir="${HOME}/.dotfiles"
    local backup_dir="${HOME}/.dotfiles-backup-$(date +%Y%m%d)"

    if [[ -d "$dotfiles_dir" ]]; then
        log "Dotfiles repo found at $dotfiles_dir"
    else
        log "No .dotfiles repo found — skipping link stage"
        ok "Dotfiles stage skipped (no repo)"
        return 0
    fi

    log "Backing up existing configs to $backup_dir..."
    mkdir -p "$backup_dir"

    local configs=(".zshrc" ".bashrc" ".config/fish" ".config/starship.toml")
    for cfg in "${configs[@]}"; do
        local src="${HOME}/$cfg"
        if [[ -e "$src" ]] && [[ ! "$src" -ef "$dotfiles_dir/${cfg##*/}" ]]; then
            cp -r "$src" "$backup_dir/" 2>/dev/null || true
        fi
    done

    # Link configs from repo
    log "Linking dotfiles..."
    for cfg in .zshrc .bashrc .config/starship.toml; do
        if [[ -e "$dotfiles_dir/$cfg" ]]; then
            ln -sf "$dotfiles_dir/$cfg" "$HOME/$cfg" 2>/dev/null || true
        fi
    done

    ok "Dotfiles linked from $dotfiles_dir"
}

stage18_dotfiles() { stage_dotfiles; }