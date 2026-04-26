# pop-os-setup — Справчник компонентов

## Описание

**pop-os-setup** — автоматизированный скрипт настройки Pop!_OS 24.04 с NVIDIA. Устанавливает, настраивает и защищает систему в идемпотентном режиме: повторный запуск безопасен.

---

## 📦 Что устанавливает pop-os-setup

### 🖥️ System

| # | Компонент | Стадия | Профиль | Описание |
|---|----------|--------|---------|----------|
| 1 | **System Update** | `stage02_update.sh` | все | `apt update + upgrade` — обновление пакетного индекса и установка последних версий пакетов |
| 2 | **NVIDIA Drivers** | `stage03_nvidia.sh` | все (GPU) | Установка `system76-driver-nvidia` или `nvidia-driver-550` + управление графическим режимом (hybrid/dedicated) |
| 3 | **KDE Plasma Desktop** | `stage06_kde.sh` | workstation | Установка `kde-plasma-desktop` как альтернативной графической оболочки |
| 4 | **System76 Power Management** | `stage16_power.sh` | ai-dev, full | Настройка `system76-power` (только System76) + persistence mode + power limit для NVIDIA GPU |
| 5 | **System Optimization** | `stage12_optimization.sh` | все | Swappiness → 10, установка `unattended-upgrades`, настройка ZRAM |
| 6 | **Dotfiles / Shell Config** | `stage18_dotfiles.sh` | все | Бэкап существующих конфигов, линковка `.zshrc`, `.bashrc`, `starship.toml` из репозитория `~/.dotfiles` |

---

### 🛠️ Dev Tools

| # | Компонент | Стадия | Профиль | Описание |
|---|----------|--------|---------|----------|
| 7 | **Zsh + Oh My Zsh** | `stage05_zsh.sh` | все | Zsh как login shell + Oh My Zsh + плагины `git zsh-autosuggestions zsh-syntax-highlighting` |
| 8 | **Neovim** | `stage22_neovim.sh` | workstation, ai-dev, full | Neovim (AppImage, latest) + базовый `init.lua` с настройками редактора |
| 9 | **Docker Engine + Compose** | `stage17_docker_compose.sh` | workstation, ai-dev, full | Docker Engine + Docker Compose v2 + Portainer (опционально) + добавление пользователя в группу `docker` |
| 10 | **SSH Keys + GPG + YubiKey** | `stage24_ssh_gpg.sh` | workstation, ai-dev, full | ED25519 SSH-ключ + GPG-агент для YubiKey + настроенный `~/.ssh/config` для GitHub/GitLab |

---

### 🤖 AI Stack

| # | Компонент | Стадия | Профиль | Описание |
|---|----------|--------|---------|----------|
| 11 | **Python + AI Stack** | `stage08_python_ai.sh` | ai-dev | Python 3, pip, PyTorch (CPU), TensorFlow, JupyterLab, Transformers + Accelerate |
| 12 | **CUDA Toolkit + cuDNN** | `stage09_cuda.sh` | ai-dev, full | CUDA 12.4 + cuDNN 8 — верификация через `nvcc --version` |
| 13 | **GPU Monitoring** | `stage20_gpu_monitoring.sh` | ai-dev, full | NVIDIA GPU exporter (Docker-контейнер на порту 9445) для Prometheus/Grafana |
| 14 | **k3s Kubernetes** | `stage14_k8s.sh` | full | k3s single-node + `kubeconfig` в `~/.kube/config` для `kubectl` |
| 15 | **Slurm Workload Manager** | `stage15_slurm.sh` | cluster | Клиентские пакеты `munge` + `slurm-client` для подключения к Slurm-кластеру |

---

### 🐳 Containers

| # | Компонент | Стадия | Профиль | Описание |
|---|----------|--------|---------|----------|
| 16 | **Docker Engine** | `stage17_docker_compose.sh` | workstation, ai-dev, full | Установка Docker Engine через безопасный скрипт (без `curl \| sh`) + демон `dockerd` |
| 17 | **Docker Compose v2** | `stage17_docker_compose.sh` | workstation, ai-dev, full | `docker compose` как плагин (не отдельный бинарник) |
| 18 | **Portainer** | `stage17_docker_compose.sh` | workstation, ai-dev, full | Веб-интерфейс для управления Docker: `http://localhost:9000` |
| 19 | **Monitoring Stack** | `stage19_monitoring.sh` | full, ai-dev | Prometheus (9090) + Grafana (3000) + node-exporter (9100) — все в Docker Compose |
| 20 | **GPU Monitoring (DCGM)** | `stage20_gpu_monitoring.sh` | ai-dev, full | `nvidia-exporter` контейнер на порту 9445 для сбора GPU-метрик |

---

### 🖥️ Desktop

| # | Компонент | Стадия | Профиль | Описание |
|---|----------|--------|---------|----------|
| 21 | **KDE Plasma** | `stage06_kde.sh` | workstation | Полная установка KDE Plasma Desktop как альтернативной оболочки |
| 22 | **System Notifications** | `stage23_notifications.sh` | workstation, ai-dev, full | systemd user-timers: GPU-температура (каждые 5 мин, ≥80°C), проверка обновлений (ежедневно), место на диске (еженедельно) |
| 23 | **Dotfiles** | `stage18_dotfiles.sh` | все | Линковка конфигов из `~/.dotfiles` с бэкапом старых |

---

### 🔒 Security

| # | Компонент | Стадия | Профиль | Описание |
|---|----------|--------|---------|----------|
| 24 | **UFW Firewall** | `stage10_hardening.sh` | все | `deny incoming / allow outgoing` + правила SSH из локальных сетей |
| 25 | **fail2ban** | `stage10_hardening.sh` | все | Защита SSH от brute-force: бан на 10 мин после 5 попыток |
| 26 | **Kernel Hardening (sysctl)** | `stage10_hardening.sh` | все | `kptr_restrict=2`, `dmesg_restrict=1`, `ptrace_scope=2`, `tcp_syncookies=1`, отключение source routing и redirect |
| 27 | **Unattended Security Upgrades** | `stage10_hardening.sh` | все | Автоматическая установка security-обновлений через `unattended-upgrades` |
| 28 | **SSH Server** | `stage11_ssh.sh` | все | `openssh-server` + автозапуск через systemd |
| 29 | **Tailscale VPN** | `stage13_tailscale.sh` | full, cluster | Mesh-VPN с поддержкой subnet routing + Funnel (443) + IP forwarding |
| 30 | **Backup & Recovery** | `stage25_backup.sh` | все | Timeshift (снапшоты: monthly×2, weekly×3, daily×5) + `pop-os-backup` rsync-скрипт + cron (Sun 03:00) |
| 31 | **Cron Jobs** | `stage21_cron.sh` | все | Задачи: очистка логов (Mon 04:00), security-updates (Tue 05:00), проверка диска (Daily 08:00), backup reminder (bi-weekly 09:00) |

---

## ⚙️ Профили

Профиль задаётся переменной `PROFILE` при запуске:

| Профиль | Стадии |
|---------|--------|
| `workstation` | 01 → 05 → 06 → 10 → 11 → 17 → 18 → 21 → 22 → 23 → 24 → 25 → 26 |
| `ai-dev` | 01 → 02 → 03 → 05 → 08 → 09 → 10 → 11 → 12 → 17 → 18 → 19 → 20 → 21 → 22 → 23 → 24 → 25 → 26 |
| `full` | 01 → 02 → 03 → 05 → 08 → 09 → 10 → 11 → 12 → 13 → 14 → 16 → 17 → 18 → 19 → 20 → 21 → 22 → 23 → 24 → 25 → 26 |
| `cluster` | 01 → 10 → 13 → 14 → 15 → 21 → 25 → 26 |

### Профиль → Таблица компонентов

| Компонент | Workstation | AI-Dev | Full | Cluster |
|-----------|:-----------:|:------:|:----:|:--------:|
| Zsh | ✅ | ✅ | ✅ | — |
| Neovim | ✅ | ✅ | ✅ | — |
| Docker + Compose | ✅ | ✅ | ✅ | — |
| Portainer | optional | optional | optional | — |
| Python + AI Stack | — | ✅ | ✅ | — |
| CUDA + cuDNN | — | ✅ | ✅ | — |
| GPU Monitoring | — | ✅ | ✅ | — |
| k3s Kubernetes | — | — | ✅ | ✅ |
| Slurm | — | — | — | ✅ |
| Monitoring Stack | — | ✅ | ✅ | — |
| KDE Plasma | ✅ | — | — | — |
| System76 Power | — | ✅ | ✅ | — |
| Tailscale VPN | — | — | ✅ | ✅ |
| System Update | — | ✅ | ✅ | — |
| NVIDIA Drivers | ✅ | ✅ | ✅ | — |
| Dotfiles | ✅ | ✅ | ✅ | ✅ |
| SSH + GPG + YubiKey | ✅ | ✅ | ✅ | — |
| Notifications | ✅ | ✅ | ✅ | — |
| Backup & Recovery | ✅ | ✅ | ✅ | ✅ |
| Hardening (UFW + fail2ban + sysctl) | ✅ | ✅ | ✅ | ✅ |
| Cron Jobs | ✅ | ✅ | ✅ | ✅ |
| SSH Server | ✅ | ✅ | ✅ | — |

---

## 🔑 Критичность

| Уровень | Значение | Описание |
|---------|----------|----------|
| **REQUIRED** | Обязательный | Без него система неработоспособна или установка невозможна |
| **OPTIONAL** | Опциональный | Ставится только при явном флаге или профиле |
| **RECOMMENDED** | Рекомендуемый | Ставится по умолчанию, можно отключить флагом |

| Компонент | Критичность |
|-----------|:-----------:|
| Pre-flight Checks (stage 01) | **REQUIRED** |
| System Update (stage 02) | **RECOMMENDED** |
| NVIDIA Drivers (stage 03) | **RECOMMENDED** |
| Zsh + Oh My Zsh (stage 05) | **RECOMMENDED** |
| System Hardening (stage 10) | **RECOMMENDED** |
| Docker + Compose (stage 17) | **RECOMMENDED** |
| CUDA + cuDNN (stage 09) | **OPTIONAL** (ai-dev, full) |
| k3s Kubernetes (stage 14) | **OPTIONAL** (full, cluster) |
| Tailscale VPN (stage 13) | **OPTIONAL** (full, cluster) |
| Monitoring Stack (stage 19) | **OPTIONAL** (ai-dev, full) |
| Portainer (stage 17) | **OPTIONAL** |
| Slurm (stage 15) | **OPTIONAL** (cluster) |
| KDE Plasma (stage 06) | **OPTIONAL** (workstation) |

---

## 🧩 Архитектура stages

```
pop-os-setup/
├── pop-os-setup.sh          # Main entry — выбор профиля, загрузка lib/, последовательный запуск stages
├── lib/
│   ├── bootstrap.sh          # Загрузка lib/*.sh в правильном порядке
│   ├── logging.sh             # step(), ok(), warn(), err(), info(), log(), log_sep()
│   ├── utils.sh              # get_target_user, pkg_installed, has_nvidia, is_service_active, backup_file…
│   ├── installer.sh          # install_oh_my_zsh_safe, install_neovim_safe, install_tailscale_safe,
│   │                          #   install_k3s_safe, safe_download, generate_random_password…
│   └── profiles.sh           # Профили workstation / ai-dev / full / cluster
└── stages/
    ├── stage01_preflight.sh  # Проверки: структура, sudo, OS, disk space, network, existing installs
    ├── stage02_update.sh      # apt update + upgrade
    ├── stage03_nvidia.sh      # NVIDIA drivers (System76 или vanilla)
    ├── stage05_zsh.sh         # Zsh + Oh My Zsh
    ├── stage06_kde.sh         # KDE Plasma Desktop
    ├── stage08_python_ai.sh  # Python + AI Stack (PyTorch, TensorFlow, Jupyter, Transformers)
    ├── stage09_cuda.sh       # CUDA Toolkit 12.4 + cuDNN 8
    ├── stage10_hardening.sh   # UFW + fail2ban + sysctl + unattended-upgrades
    ├── stage11_ssh.sh        # OpenSSH server
    ├── stage12_optimization.sh # Swappiness + unattended-upgrades + ZRAM
    ├── stage13_tailscale.sh   # Tailscale VPN
    ├── stage14_k8s.sh        # k3s single-node
    ├── stage15_slurm.sh      # Slurm client
    ├── stage16_power.sh      # System76 power + GPU tuning
    ├── stage17_docker_compose.sh # Docker Engine + Compose v2 + Portainer
    ├── stage18_dotfiles.sh    # Dotfiles symlink
    ├── stage19_monitoring.sh # Prometheus + Grafana + node-exporter
    ├── stage20_gpu_monitoring.sh # nvidia-exporter (DCGM)
    ├── stage21_cron.sh       # Cron jobs (log cleanup, security updates, disk check, backup reminder)
    ├── stage22_neovim.sh     # Neovim (latest AppImage) + init.lua
    ├── stage23_notifications.sh # systemd user-timers (GPU temp, updates, disk)
    ├── stage24_ssh_gpg.sh    # ED25519 SSH key + GPG/YubiKey agent
    ├── stage25_backup.sh     # Timeshift + rsync backup script
    └── stage26_final.sh      # Final verification + report
```

---

## 🚀 Быстрый старт

```bash
# Клонирование и запуск с профилем
git clone https://github.com/mahaasur13-sys/pop-os-setup.git
cd pop-os-setup
sudo PROFILE=ai-dev ./pop-os-setup.sh

# Только конкретные stages
sudo ENABLE_ZSH=1 ENABLE_CUDA=1 PROFILE=ai-dev ./pop-os-setup.sh

# Проверка синтаксиса
make lint

# Dry-run (только pre-flight + список что будет)
make verify
```
