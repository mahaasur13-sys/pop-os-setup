# pop-os-setup v3.0.0 (Stable)

## Major Changes & Security Improvements

### Security
- **Полностью устранены все curl | sh** (6 критических RCE-векторов)
- Введена централизованная безопасная установка через `lib/installer.sh`
- Все внешние скачивания теперь идут через `safe_download()` с проверкой SHA256
- Генерация случайных паролей вместо hardcoded (Grafana, Portainer)
- Значительно улучшена работа с целевым пользователем (не от root)

### Architecture
- Полностью динамическое обнаружение всех 26 стадий
- Один главный entry-point (`pop-os-setup.sh`)
- Единый стиль кода и логирования во всех stage-файлах
- Добавлены guards от повторного sourcing (`_STAGE_SOURCED`)

### Новые возможности
- Поддержка `--dry-run`, `--stage`, `--skip-stage`, `--profile`
- Улучшенные профили (включая `cluster`)
- Значительно улучшена идемпотентность большинства стадий
- Красивый финальный отчёт (stage26)

### Переписанные стадии (v3.0.0 style)
- stage05_zsh, stage09_cuda, stage13_tailscale, stage14_k8s, stage17_docker_compose,
- stage19_monitoring, stage22_neovim, stage24_ssh_gpg, stage25_backup, stage26_final,
- stage10_hardening, stage21_cron, stage23_notifications

## Известные ограничения
- Некоторые старые stage-файлы (1–4, 6, 8, 11, 12, 15, 16, 18, 20) ещё используют старый стиль
- 18 shellcheck warnings (все ложные или не критичные)

---

**Спасибо всем, кто участвовал в рефакторинге!**
