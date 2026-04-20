#!/bin/bash
#===============================================================================
# Stage 22 — Neovim (latest) + basic config
#===============================================================================
# Профиль: workstation, ai-dev, full
# Использует: install_neovim_safe из lib/installer.sh
#===============================================================================

# Защита от повторного sourcing + поддержка автономного запуска
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

_STAGE_SOURCED=yes

stage_neovim() {
    step "NEOVIM" "22"

    # Проверка флага из профиля
    if [[ "${ENABLE_NEOVIM:-1}" != "1" ]]; then
        ok "Neovim installation skipped (ENABLE_NEOVIM=0)"
        return 0
    fi

    # Установка через безопасную функцию (идемпотентная)
    case "$(install_neovim_safe)" in
        0) ok "Neovim installed successfully" ;;
        2) ok "Neovim already installed — skipping" ;;
        1) err "Neovim installation failed" ; return 1 ;;
    esac

    # Создание базового ~/.config/nvim для целевого пользователя
    local target_user="${SUDO_USER:-${USER:-root}}"
    local home
    home="$(get_user_home "$target_user")"
    local nvim_dir="${home}/.config/nvim"
    local init_file="${nvim_dir}/init.lua"

    if [[ "$target_user" == "root" || -z "$home" || "$home" == "/" ]]; then
        warn "Cannot determine valid user home — skipping user config"
    else
        log "Setting up user config for ${target_user}"

        ensure_dir "$nvim_dir"

        if [[ ! -f "$init_file" ]]; then
            cat > "$init_file" << 'NVIMEOF'
-- Neovim base config (pop-os-setup stage22)
vim.g.mapleader = " "
vim.g.maplocalleader = " "

-- UI
vim.opt.number = true
vim.opt.relativenumber = true
vim.opt.cursorline = true
vim.opt.mouse = "a"
vim.opt.swapfile = false
vim.opt.backup = false
vim.opt.writebackup = false
vim.opt.termguicolors = true
vim.opt wildmenu = true
vim.opt wildmode = "list:longest,full"

-- Indentation
vim.opt.expandtab = true
vim.opt.shiftwidth = 4
vim.opt.tabstop = 4
vim.opt.softtabstop = 4
vim.opt.smartindent = true

-- Behaviour
vim.opt.hidden = true
vim.opt.autoread = true
vim.opt.clipboard = "unnamedplus"
vim.opt.laststatus = 3
vim.opt.splitright = true
vim.opt.splitbelow = true
vim.opt.ignorecase = true
vim.opt.smartcase = true
vim.opt.scrolloff = 8
vim.opt.sidescrolloff = 8
vim.opt.isfname:append("@-@")

-- Performance
vim.opt.updatetime = 100
vim.opt.redrawtime = 1500

-- Basic keybinds
vim.keymap.set("n", "<leader>w", "<cmd>write<cr>", { desc = "Write buffer" })
vim.keymap.set("n", "<leader>q", "<cmd>quit<cr>", { desc = "Quit" })
vim.keymap.set("n", "<leader>h", "<cmd>nohlsearch<cr>", { desc = "Clear highlight" })
NVIMEOF
            ok "Created ${init_file}"
        else
            ok "User init.lua already exists — skipping"
        fi
    fi

    ok "Neovim stage complete"
    return 0
}

# Совместимость со старым вызовом
stage22_neovim() {
    stage_neovim "$@"
}
