#!/bin/bash
#===============================================================================
# lib/_path.sh — INTERNAL: Deterministic LIBDIR resolution (v4.0.0)
#===============================================================================
# Принцип: ищем вверх по директориям пока не найдём lib/logging.sh
# Никаких относительных путей. Никаких guesswork.
#===============================================================================

_detect_LIBDIR() {
    local search_from="${1:-}"
    local max_depth=8
    local depth=0

    # Нормализуем symlink
    local current
    if [[ -L "$search_from" ]]; then
        current=$(readlink -f "$search_from" 2>/dev/null) || current="$search_from"
    elif [[ -f "$search_from" ]]; then
        current=$(dirname "$search_from")
    else
        current="$search_from"
    fi

    while (( depth < max_depth )); do
        local candidate="${current}/lib"
        if [[ -f "${candidate}/logging.sh" && -f "${candidate}/utils.sh" ]]; then
            echo "$(realpath "$candidate" 2>/dev/null || echo "$candidate")"
            return 0
        fi

        local parent=$(dirname "$current" 2>/dev/null)
        if [[ "$parent" == "$current" || -z "$parent" ]]; then
            break
        fi
        current="$parent"
        ((depth++)) || true
    done

    echo "[_path.sh] FATAL: Cannot resolve LIBDIR" >&2
    echo "[_path.sh] Search started from: $search_from" >&2
    echo "[_path.sh] BASH_SOURCE[0]=${BASH_SOURCE[0]:-}" >&2
    echo "[_path.sh] BASH_SOURCE[1]=${BASH_SOURCE[1]:-}" >&2
    echo "[_path.sh] PWD=$PWD" >&2
    return 1
}

_init_paths() {
    # Приоритет: BASH_SOURCE[1] (main script) > BASH_SOURCE[0] (sourced) > env override
    local primary="${BASH_SOURCE[1]:-}"
    local secondary="${BASH_SOURCE[0]:-}"
    local override="${POP_OS_SETUP_DIR:-}"

    if [[ -n "$primary" ]]; then
        local d="$(_detect_LIBDIR "$primary")" && { echo "$d"; return 0; }
    fi

    if [[ -n "$secondary" ]]; then
        local d="$(_detect_LIBDIR "$secondary")" && { echo "$d"; return 0; }
    fi

    if [[ -n "$override" ]]; then
        local d="$(_detect_LIBDIR "$override")" && { echo "$d"; return 0; }
    fi

    # Последняя попытка — поиск от PWD
    local d="$(_detect_LIBDIR "$PWD")" && { echo "$d"; return 0; }

    return 1
}

# Вычисляем один раз при загрузке
LIBDIR="$(_init_paths)" || {
    echo "FATAL: LIBDIR resolution failed" >&2
    return 1
}

export LIBDIR
