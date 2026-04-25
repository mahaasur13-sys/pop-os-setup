# pop-os-setup — Описание компонентов установки

> Формируется автоматически из `stages/` и `profiles/`
> ver: v11.3 | profiles: workstation · ai-dev · full · cluster

---

## 📋 Общая архитектура

**Система:** Deterministic Intent-Driven Provisioning — каждая установка проходит через три слоя: **Intent → CESM State → Physical → Reconciliation → Intent**.

**Поток:**
```
Intent (.intent.json) → [CESM State] → Physical → [Reconciliation] → Intent validation
```

**Профили:**

| Профиль | Назначение | CUDA | Docker | AI Stack | K8s | Slurm | SSH | Tailscale | Hardening |
|---------|-----------|------|--------|----------|-----|-------|-----|-----------|-----------|
| `workstation` | AI/Dev workstation для одного пользователя | — | ✅ | ✅ | — | — | — | — | ✅ |
| `ai-dev` | ML-исследователь, GPU-нагрузки | ✅ | ✅ | ✅ | — | — | — | — | ✅ |
| `full` | Power user / home lab / cluster node | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cluster` | Вычислительный кластер (k3s + Slurm) | ✅ | ✅ | ✅ | ✅ | ✅ | — | — | ✅ |

---

## 🗂️ Стадии установки (Stages)

### Этап 1 — Подготовка

#### Stage 01 — Pre-flight Checks
- **Категория:** System
- **Что делает:** Проверяет структуру проекта, OS-совместимость, права root, место на диске, сетевой доступ, наличие базовых утилит (curl, git, jq)
- **Результат:** `structure_valid`, `network_ok`, `sudo_ok`, `disk_ok`
- **Критичность:** REQUIRED (все профили)

---

#### Stage 02–08 — Auto Repair
- **Категория:** System
- **Что делает:** Набор служебных этапов для консистентности (могут включать исправления lib-файлов, профилей, bootstrap-логики)
- **Критичность:** REQUIRED (все профили)

---

### Этап 2 — Базовая среда

#### Stage 04 — Dev Tools
- **Категория:** Dev Tools
- **Что делает:** Установка базовых инструментов разработки: `build-essential`, `git`, `curl`, `wget`, `vim`, `htop`, `ncdu`, `tree`, `jq`, `gdisk`, `smartmontools`
- **Критичность:** REQUIRED (все профили)

---

#### Stage 05 — Zsh + Oh My Zsh
- **Категория:** Desktop
- **Что делает:** Устанавливает Zsh как альтернативную оболочку, ставит **Oh My Zsh** (менеджер плагинов для Zsh), добавляет плагины `zsh-autosuggestions` и `zsh-syntax-highlighting`
- **Зачем:** Удобный терминал с автодополнением и подсветкой синтаксиса
- **Профиль:** все (workstation, ai-dev, full, cluster)
- **Критичность:** RECOMMENDED

---

#### Stage 06 — KDE Plasma
- **Категория:** Desktop
- **Что делает:** Установка KDE Plasma (если выбрана)
- **Профиль:** workstation, ai-dev, full
- **Критичность:** OPTIONAL (по профилю)

---

#### Stage 07 — Docker
- **Категория:** Containers
- **Что делает:** Установка **Docker Engine**, включение systemd-сервиса, добавление текущего пользователя в группу `docker`, включение Docker в автозапуск
- **Профиль:** workstation, ai-dev, full, cluster
- **Критичность:** RECOMMENDED

---

### Этап 3 — AI Stack

#### Stage 08 — Python + AI Tools
- **Категория:** AI Stack
- **Что делает:** Установка Python (если нет), `pip`, `venv`, `jupyter`, `ollama` (локальные LLM), `pyenv` (управление версиями Python)
- **Профиль:** workstation, ai-dev, full
- **Критичность:** RECOMMENDED

---

#### Stage 09 — CUDA Toolkit + cuDNN
- **Категория:** AI Stack
- **Что делает:** Установка **NVIDIA CUDA Toolkit 12.4** и **cuDNN** через официальный NVIDIA keyring (безопасная загрузка с верификацией SHA256). Настраивает `PATH` и `LD_LIBRARY_PATH` в `/etc/profile.d/cuda.sh`
- **Требует:** NVIDIA GPU + NVIDIA drivers (stage 03)
- **Профиль:** ai-dev, full
- **Критичность:** OPTIONAL (по профилю)

---

### Этап 4 — Безопасность

#### Stage 10 — System Hardening
- **Категория:** Security
- **Что делает:**
  - **UFW firewall** — default deny incoming, allow outgoing; при `ENABLE_SSH=1` открывает порт 22 только из `192.168.10.0/24` и `10.0.0.0/8` (Tailscale)
  - **fail2ban** — защита SSH от brute-force (3 попытки, бан 30 мин)
  - **sysctl hardening** — kptr_restrict, dmesg_restrict, ptrace_scope, TCP SYN cookies, отключение source route и ICMP redirects
  - **unattended-upgrades** — автоматические обновления безопасности
- **Профиль:** все
- **Критичность:** RECOMMENDED

---

#### Stage 24 — SSH + GPG
- **Категория:** Security
- **Что делает:** Настройка **OpenSSH server** (при `ENABLE_SSH=1`), генерация/добавление SSH-ключей, настройка **GPG-agent**, SSH-agent forwarding
- **Профиль:** full, cluster
- **Критичность:** OPTIONAL (по профилю)

---

### Этап 5 — Networking

#### Stage 13 — Tailscale
- **Категория:** System
- **Что делает:** Установка и настройка **Tailscale** (VPN от WireGuard) для безопасного доступа к кластеру из любой точки; настраивает SSH-over-Tailscale
- **Профиль:** full
- **Критичность:** OPTIONAL (по профилю)

---

#### Stage 11 — SSH Setup
- **Категория:** System
- **Что делает:** Первичная настройка SSH (sshd_config, ключи)
- **Профиль:** full, cluster
- **Критичность:** OPTIONAL

---

### Этап 6 — Dev Tools / Optimization

#### Stage 12 — System Optimization
- **Kategorie:** System
- **Что делает:** Настройка планировщика I/O (`noop`/`mq-deadline`), transparent hugepages, earlyoom, swappiness, файловые дескрипторы
- **Критичность:** OPTIONAL

---

#### Stage 22 — Neovim
- **Kategorie:** Dev Tools
- **Что делает:** Установка Neovim (latest AppImage), настройка базового `init.vim` / `init.lua` с минимум плагинов (файловый менеджер, LSP-клиент, терминал)
- **Критичность:** OPTIONAL

---

### Этап 7 — Container Orchestration

#### Stage 14 — Kubernetes (k3s)
- **Kategorie:** Containers
- **Что делает:** Установка **k3s** (lightweight Kubernetes) — master или agent в зависимости от конфигурации; настройка `kubectl` config
- **Профиль:** full, cluster
- **Критичность:** OPTIONAL

---

#### Stage 17 — Docker Compose
- **Kategorie:** Containers
- **Что делает:** Установка `docker-compose` (standalone v2) и `docker-compose-switch` (для переключения между версиями)
- **Критичность:** OPTIONAL

---

### Этап 8 — HPC / Batch

#### Stage 15 — Slurm
- **Kategorie:** System
- **Что делает:** Установка и настройка **Slurm** (workload manager для HPC-кластеров) — munge, slurmctld, slurmd
- **Профиль:** cluster, full
- **Критичность:** OPTIONAL

---

### Этап 9 — Hardware / Power

#### Stage 16 — Power Tuning
- **Kategorie:** System
- **Что делает:** Настройка CPU governor (`performance`/`powersave`), TLP для управления питанием ноутбука (или десктопа), опции NVIDIA persistence mode
- **Критичность:** OPTIONAL

---

#### Stage 20 — GPU Monitoring
- **Kategorie:** System
- **Что делает:** Установка `nvidia-dcgm` (Data Center GPU Manager) для мониторинга GPU в реальном времени; prometheus-экспортер
- **Профиль:** full, ai-dev (при ENABLE_CUDA=1)
- **Критичность:** OPTIONAL

---

### Этап 10 — Observability

#### Stage 19 — Monitoring
- **Kategorie:** System
- **Что делает:** Установка **Prometheus** + **Grafana** (или node-exporter) для системного мониторинга
- **Профиль:** full, workstation, ai-dev
- **Критичность:** OPTIONAL

---

#### Stage 21 — Cron Jobs
- **Kategorie:** System
- **Что делает:** Настройка scheduled tasks — очистка логов, проверка обновлений, бэкап состояния
- **Критичность:** OPTIONAL

---

### Этап 11 — User Experience

#### Stage 18 — Dotfiles
- **Категория:** Desktop
- **Что делает:** Синхронизация пользовательских dotfiles (`.bashrc`, `.vimrc`, алиасы, git config) через Git-репозиторий dotfiles
- **Критичность:** OPTIONAL

---

#### Stage 23 — Notifications
- **Категория:** Desktop
- **Что делает:** Настройка уведомлений о завершении установки (через `notify-send` / `ntfy` / Telegram-бот)
- **Критичность:** OPTIONAL

---

### Этап 12 — Data Safety

#### Stage 25 — Backup
- **Категория:** System
- **Что делает:** Настройка **BorgBackup** или **Restic** для инкрементного бэкапа важных директорий (`/etc`, `$HOME`); cron-расписание
- **Критичность:** OPTIONAL

---

### Этап 13 — Финализация

#### Stage 26 — Final
- **Категория:** System
- **Что делает:** Финальная проверка всех сервисов, генерация итогового отчёта, логирование результата в `setup.jsonl`
- **Критичность:** REQUIRED

---

## 📊 Сводная таблица: профиль → компоненты

| Компонент | workstation | ai-dev | full | cluster |
|-----------|:-----------:|:------:|:----:|:-------:|
| Zsh + Oh My Zsh | ✅ | ✅ | ✅ | ✅ |
| KDE Plasma | ✅ | ✅ | ✅ | — |
| Docker | ✅ | ✅ | ✅ | ✅ |
| Python + AI tools | ✅ | ✅ | ✅ | ✅ |
| CUDA + cuDNN | — | ✅ | ✅ | ✅ |
| Hardening (UFW + fail2ban + sysctl) | ✅ | ✅ | ✅ | ✅ |
| SSH server | — | — | ✅ | — |
| Tailscale | — | — | ✅ | — |
| k3s | — | — | ✅ | ✅ |
| Slurm | — | — | ✅ | ✅ |
| Monitoring (Prometheus/Grafana) | ✅ | ✅ | ✅ | — |
| GPU Monitoring (DCGM) | — | ✅ | ✅ | — |
| Docker Compose | ✅ | ✅ | ✅ | ✅ |
| Power Tuning | — | — | ✅ | — |
| Neovim | ✅ | ✅ | ✅ | ✅ |
| Backup (Borg/Restic) | — | — | ✅ | — |

---

## 🧩 Библиотеки (lib/)

| Файл | Назначение |
|------|-----------|
| `lib/logging.sh` | Централизованный логинг с уровнями `step`, `ok`, `warn`, `err`, `info`; запись в `setup.jsonl` |
| `lib/utils.sh` | `get_target_user`, `get_user_home`, `pkg_installed`, `command_exists`, `has_nvidia`, `backup_file`, `append_once`, `apply_sysctl` |
| `lib/installer.sh` | `install_oh_my_zsh_safe`, `safe_download` (с SHA256), `require_cmd` |
| `lib/profiles.sh` | Профильные переменные и функция `apply_profile_<name>` |
| `lib/bootstrap.sh` | Инициализация переменных окружения |

---

## 🔒 Безопасность (важные детали)

- **safe_download** — верификация SHA256 при скачивании файлов (keyring, артефакты)
- **idempotency** — `is_installed`, `is_done`, `mark_done` — повторный запуск безопасен
- **UFW default deny** — весь входящий трафик заблокирован по умолчанию
- **fail2ban** — SSH-бан после 3 неудачных попыток на 30 минут
- **sysctl** — kptr_restrict, dmesg_restrict, ptrace_scope, SYN cookies, откл. source route
- **no curl|sh** — никаких опасных установщиков через пайп

---

## 🚀 Запуск

```bash
# Полная установка (все компоненты)
sudo ./pop-os-setup.sh --profile full

# Только AI/Dev workstation
sudo ./pop-os-setup.sh --profile ai-dev

# Один stage
sudo ./pop-os-setup.sh --stage 10

# Dry-run
sudo ./pop-os-setup.sh --dry-run --profile full
```
