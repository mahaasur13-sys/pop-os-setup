# pop-os-setup: Компоненты и программы установки

## Описание

`pop-os-setup` — это скрипт детерминированной идемпотентной установки для Pop!_OS / Ubuntu. Он автоматизирует настройку рабочей станции за ~15–25 минут, проходя 26 стадий установки.

> Все загрузки — безопасные: никаких `curl | sh`. Каждый пакет сначала скачивается, проверяется по SHA256, затем устанавливается локально.

---

## Профили установки

Профиль определяет, какие компоненты будут установлены. Задаётся флагом `--profile`.

| Профиль | Назначение | CUDA | Docker | AI Stack | VPN | K8s | Hardening |
|---------|-----------|------|--------|----------|-----|-----|-----------|
| `workstation` | Разработка / AI Practitioner | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |
| `ai-dev` | ML-исследователь / GPU-тяжёлый | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| `full` | Всё включено | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cluster` | Сервер / кластер | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ |

---

## Стадии установки

### 🔧 Системные (Stage 01–04)

#### Stage 01 — Pre-flight Checks
```
Проверяет: структура файлов, root-доступ, OS (Pop!_OS/Ubuntu), место на диске,
сетевое подключение, наличие docker/nvim/zsh/kubectl.
Действует: прерывает установку, если места < 10 ГБ или нет root.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| curl | HTTP-клиент | Скачивание пакетов и зависимостей | REQUIRED |
| git | Система контроля версий | Клонирование репозиториев | REQUIRED |
| jq | JSON-парсер | Обработка JSON-состояния (CESM) | REQUIRED |

**Файлы**: `lib/logging.sh`, `lib/utils.sh`, `lib/profiles.sh`, `lib/bootstrap.sh`
**Контракт**: `provides structure_valid, network_ok, sudo_ok`

---

#### Stage 02–08 — Auto-Repair (дедупликация + исправления)
```
Многоступенчатая система самовосстановления: nvidia-drivers, dev-tools,
pip/conda, NVIDIA CUDA drivers, oh-my-zsh, Docker, Python AI-стек.
Каждый stage idempotent (повторный запуск безвреден).
```

---

### 🖥 Рабочий стол (Stage 05–08)

#### Stage 05 — Zsh + Oh My Zsh
```
Устанавливает: Zsh (оболочка), Oh My Zsh (фреймворк плагинов),
zsh-autosuggestions, zsh-syntax-highlighting.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Zsh | Современная оболочка | Замена bash с улучшенным автодополнением | OPTIONAL |
| Oh My Zsh | Менеджер плагинов | Удобная установка тем и плагинов | OPTIONAL |
| zsh-autosuggestions | Автодополнение из истории | Быстрый ввод команд | Плагин |
| zsh-syntax-highlighting | Подсветка синтаксиса | Видишь ошибки до выполнения | Плагин |

**Профиль**: все (workstation, ai-dev, full, cluster)
**Контракт**: `provides shell_ready`

---

#### Stage 06 — KDE Plasma Desktop
```
Устанавливает: kde-plasma-desktop, plasma-workspace, весь набор KDE-приложений.
Альтернатива: можно использовать GNOME (по умолчанию в Pop!_OS).
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| kde-plasma-desktop | Рабочий стол KDE Plasma | Полная замена рабочего стола | OPTIONAL |
| plasma-workspace | Менеджер сессий | Оконный менеджер, панели, виджеты | OPTIONAL |

**Профиль**: workstation, ai-dev, full

---

### 🤖 AI Stack (Stage 08–09)

#### Stage 08 — Python + AI-стек
```
Устанавливает: Python 3.x, pip, conda/mamba, PyTorch, TensorFlow,
Jupyter Notebook/Lab, Ollama (локальные LLM).
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Python 3 | Язык программирования | Основной язык ML/AI | REQUIRED |
| pip | Менеджер пакетов Python | Установка Python-библиотек | REQUIRED |
| conda/mamba | Менеджер окружений | Изоляция ML-проектов, управление версиями | OPTIONAL |
| PyTorch | Библиотека машинного обучения | Обучение и инференс нейросетей | AI |
| TensorRT | Оптимизация inference | Ускорение моделей на GPU | AI |
| Jupyter Notebook/Lab | Интерактивные блокноты | Разработка и эксперименты с данными | AI |
| Ollama | Локальные LLM | Запуск открытых моделей (Llama, Mistral) локально | AI |
| transformers | HF Transformers | Работа с предобученными моделями | AI |

**Профиль**: ai-dev, full
**Контракт**: `provides ai_stack_ready, python_ready`

---

#### Stage 09 — CUDA Toolkit + cuDNN
```
Устанавливает: NVIDIA CUDA keyring → cuda-toolkit-12-4, libcudnn8, libcudnn8-dev.
Настраивает: PATH, LD_LIBRARY_PATH через /etc/profile.d/cuda.sh
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| CUDA Toolkit 12-4 | Среда разработки GPU NVIDIA | Компиляция и запуск GPU-кода | REQUIRED (ai-dev) |
| cuDNN | CUDA Deep Neural Network library | Ускорение DNN-операций в PyTorch/TensorFlow | REQUIRED (ai-dev) |
| CUDA keyring | Пакетный ключ NVIDIA | Аутентификация пакетов из NVIDIA repo | REQUIRED |

**Профиль**: ai-dev, full
**Требует**: NVIDIA GPU + NVIDIA drivers (stage03)
**Версия**: CUDA 12.4
**Контракт**: `provides cuda_ready`

---

### 🔐 Безопасность (Stage 10)

#### Stage 10 — System Hardening
```
Устанавливает и настраивает: UFW firewall, fail2ban, sysctl hardening,
unattended-upgrades (автоматические обновления безопасности).
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| UFW (Uncomplicated Firewall) | Firewall | Блокировка входящих соединений по умолчанию | Security |
| fail2ban | Защита от brute-force | Бан IP после 5 неудачных попыток SSH за 10 мин | Security |
| unattended-upgrades | Автообновления | Установка патчей безопасности без участия пользователя | Security |
| sysctl hardening | Настройки ядра | Защита от network-атак, скрытие kernel-инфы | Security |

**Sysctl правила**: `kernel.kptr_restrict=2`, `kernel.dmesg_restrict=1`, `net.ipv4.tcp_syncookies=1`, `net.ipv4.conf.all.rp_filter=1` и др.
**Профиль**: все
**Контракт**: `provides security_ready`

---

### 🌐 Сеть (Stage 11, 13–14)

#### Stage 11 — SSH Server
```
Устанавливает: openssh-server.
Включает и запускает сервис ssh.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| OpenSSH Server | SSH-демон | Удалённый доступ к машине по SSH | OPTIONAL |

**Профиль**: все
**Контракт**: `provides ssh_ready`

---

#### Stage 13 — Tailscale VPN
```
Устанавливает: tailscale (deb-пакет), включает IP forwarding,
настраивает Tailscale Funnel (открывает порт 443 через Tailscale).
Авторизация через TAILSCALE_AUTHKEY или интерактивно.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Tailscale | VPN-сеть Zero-config | Доступ к машине из любой точки без проброса портов | OPTIONAL |
| Tailscale Funnel | Публичный доступ | Открывает локальный порт 443 через Tailscale CDN | VPN |

**Профиль**: full, cluster
**Требует**: TAILSCALE_AUTHKEY env var
**Контракт**: `provides vpn_ready`

---

#### Stage 14 — k3s Kubernetes
```
Устанавливает: k3s (lightweight Kubernetes) в режиме single-node server.
Копирует kubeconfig в ~/.kube/config целевого пользователя.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| k3s | Kubernetes (single-node) | Оркестрация контейнеров, управление подами | OPTIONAL |
| kubectl | Kubernetes CLI | Управление кластером из командной строки | k8s |

**Профиль**: full, cluster
**Требует**: Docker (рекомендуется, но не обязателен)
**Контракт**: `provides k8s_ready`

---

### 🐳 Контейнеры (Stage 07, 17)

#### Stage 07 — Docker Engine
```
Устанавливает: Docker Engine через безопасный метод (без curl|sh).
Добавляет пользователя в группу docker.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Docker Engine | Контейнеризация | Изоляция приложений в контейнерах | REQUIRED |
| docker CLI | Управление Docker | Команды docker run, docker ps и т.д. | REQUIRED |

**Профиль**: workstation, ai-dev, full
**Контракт**: `provides docker_ready`

---

#### Stage 17 — Docker Compose + Portainer
```
Устанавливает: Docker Compose v2, Portainer (веб-интерфейс для Docker).
Добавляет пользователя в группу docker.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Docker Compose v2 | Оркестрация мультиконтейнерных приложений | docker compose up -d | REQUIRED |
| Portainer CE | Веб-UI для Docker | Управление контейнерами через браузер | OPTIONAL |
| Portainer Agent | Агент Portainer | Связь между Portainer и Docker host | Portainer component |

**Профиль**: workstation, ai-dev, full
**Порты**: 9000 (Portainer), 8000 (Portainer agent)
**Контракт**: `provides compose_ready, portainer_ready`

---

### 👨‍💻 Инструменты разработки (Stage 04, 22–24)

#### Stage 04 — Dev Tools
```
Устанавливает: build-essential, git, curl, wget, tar, gzip,
mc (Midnight Commander), htop, tree, tmux, gh (GitHub CLI).
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| build-essential | GCC, make, g++ | Компиляция ПО из исходников | REQUIRED |
| mc | Файловый менеджер | Навигация по файлам в терминале | OPTIONAL |
| htop | Диспетчер задач | Мониторинг процессов и нагрузки | OPTIONAL |
| tmux | Терминальный мультиплексор | Сессии, панели, окна в терминале | OPTIONAL |
| gh | GitHub CLI | Работа с GitHub из командной строки (PR, issue, release) | OPTIONAL |
| tree | Древовидный вывод директорий | Быстрый просмотр структуры папок | OPTIONAL |

**Профиль**: все
**Контракт**: `provides dev_tools_ready`

---

#### Stage 22 — Neovim (latest)
```
Устанавливает: Neovim (последняя версия, linux64 tarball) → /opt/neovim.
Создаёт ~/.config/nvim/init.lua с базовой конфигурацией.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Neovim | Текстовый редактор (Modal UI, vim-потомок) | Основной редактор для разработки | OPTIONAL |
| init.lua | Конфигурация Neovim | number, relative number, smartindent, clipboard, wildmenu и др. | Config |

**Профиль**: workstation, ai-dev, full
**Путь**: `/opt/neovim/bin/nvim` → symlink `/usr/local/bin/nvim`
**Контракт**: `provides editor_ready`

---

#### Stage 24 — SSH Keys + GPG + YubiKey
```
Генерирует: ED25519 SSH-ключ с passphrase (сохраняется в ~/.config/pop-os-setup/.ssh_passphrase).
Настраивает: ~/.ssh/config (github.com, gitlab.com, global defaults).
Опционально: GPG + YubiKey для SSH-агента.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| SSH Key (ED25519) | Асимметричная пара для SSH | Аутентификация на GitHub/GitLab без пароля | REQUIRED |
| ssh-agent | Хранитель ключей | Не вводить passphrase каждый раз | SSH component |
| GPG Agent | GPG-агент для SSH | Использование YubiKey как SSH-ключа | OPTIONAL |
| YubiKey | Аппаратный ключ безопасности | Защита SSH/GPG-ключей физическим токеном | OPTIONAL |

**Профиль**: workstation, ai-dev, full
**Контракт**: `provides ssh_keys_ready, gpg_ready`

---

### 📊 Мониторинг (Stage 19–20)

#### Stage 19 — Prometheus + Grafana
```
Разворачивает через Docker Compose: Prometheus + Grafana + node-exporter.
Генерирует случайный пароль для Grafana (сохраняется в ~/.config/pop-os-setup/.grafana_password).
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Prometheus | Сбор метрик + time-series DB | Мониторинг системы и сервисов | Monitoring |
| Grafana | Визуализация метрик | Дашборды, графики, алерты | Monitoring |
| node-exporter | Экспортер метрик хоста | Метрики CPU, RAM, диск, сеть | Monitoring |

**Порты**: 9090 (Prometheus), 3000 (Grafana)
**Профиль**: full, ai-dev
**Контракт**: `provides monitoring_ready`

---

#### Stage 20 — GPU Monitoring
```
Устанавливает: nvidia-container-toolkit, настраивает NVIDIA Device Plugin для k3s.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| nvidia-container-toolkit | NVIDIA runtime для Docker | Контейнеры с GPU-доступом | GPU |
| NVIDIA Device Plugin | Kubernetes device plugin | GPU в Kubernetes подах | k8s |

**Профиль**: full (ai-dev опционально)
**Требует**: NVIDIA GPU + CUDA

---

### ⏰ Автоматизация (Stage 21)

#### Stage 21 — Cron Jobs
```
Создаёт запланированные задачи (system crontab + user crontab):
```

| Задача | Расписание | Команда |
|--------|-----------|---------|
| Очистка логов | Пн 04:00 | find /var/log -name '*.log' -mtime +30 -delete |
| Проверка обновлений | Вт 05:00 | apt-get update && apt-get upgrade -y |
| Проверка диска | Ежедневно 08:00 | /usr/local/bin/pop-os-disk-check (85% threshold) |
| Напоминание о бэкапе | Каждые 14 дней 09:00 | systemd-cat напоминание |

**Профиль**: все
**Скрипты**: `/usr/local/bin/pop-os-disk-check`
**Контракт**: `provides cron_ready`

---

### 🔋 Питание (Stage 16)

#### Stage 16 — System76 Power + GPU Tuning
```
Работает ТОЛЬКО на hardware System76. Настраивает:
- system76-power graphics nvidia (режим)
- system76-power profile performance
- nvidia-smi -pm 1 (persistence mode)
- nvidia-smi -pl 250 (power limit)
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| system76-power | Утилита управления питанием System76 | Управление GPU-режимом, профилями питания | Platform |
| NVIDIA persistence mode | Удержание GPU-состояния | Не переинициализировать GPU между запросами | GPU |

**Профиль**: все (но пропускается на не-System76)
**Контракт**: `provides power_ready`

---

### 💾 Резервное копирование (Stage 25)

#### Stage 25 — Backup & Recovery
```
Устанавливает: Timeshift, rsync-backup скрипт.
Создаёт начальный snapshot Timeshift.
Настраивает cron для еженедельного бэкапа (Вс 03:00).
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| Timeshift | Системный снапшот-менеджер | Восстановление системы после сбоев | Backup |
| Timeshift snapshots | Снимки состояния системы | Откат к рабочей конфигурации | Snapshot |
| pop-os-backup | rsync-бэкап скрипт | Инкрементальный бэкап файлов | Backup |
| rsync | Синхронизация файлов | Эффективное копирование с инкрементальностью | Backup |

**Расписание**: Вс 03:00 → `/usr/local/bin/pop-os-backup /backup/pop-os`
**Снимки Timeshift**: monthly×2, weekly×3, daily×5
**Профиль**: все
**Контракт**: `provides backup_ready`

---

### 🎯 Дополнительные компоненты

#### Stage 02 — NVIDIA Drivers (из Auto-Repair)
```
Устанавливает: проприетарные NVIDIA drivers для GPU.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| NVIDIA Driver | Проприетарный драйвер GPU | GPU-ускорение, CUDA, ML workloads | REQUIRED (AI) |

---

#### Stage 03 — CUDA/NVIDIA (Auto-Repair)
```
Проверяет и устанавливает: NVIDIA driver + CUDA toolkit.
```

---

#### Stage 15 — SLURM (Cluster Workload Manager)
```
Устанавливает: SLURM (Simple Linux Utility for Resource Management).
Планировщик задач для HPC-кластеров.
```

| Компонент | Что делает | Зачем нужен | Тип |
|-----------|-----------|-------------|-----|
| SLURM | Планировщик задач / менеджер кластера | Распределение вычислений по узлам кластера | HPC |

**Профиль**: cluster

---

#### Stage 18 — Dotfiles
```
Синхронизирует и применяет: пользовательские dotfiles (.bashrc, .zshrc, .gitconfig и т.д.)
из репозитория или локальной директории.
```

---

#### Stage 23 — Desktop Notifications
```
Настраивает: уведомления на рабочем столе для завершения стадий,
результатов cron-задач, предупреждений.
```

---

#### Stage 26 — Final
```
Финальная стадия: проверка всех контрактов CESM,
генерация итогового отчёта, инструкции по следующим шагам.
```

---

## Библиотеки (lib/)

| Файл | Назначение |
|------|-----------|
| `lib/logging.sh` | step(), ok(), warn(), err(), log(), log_sep() |
| `lib/utils.sh` | get_target_user, get_user_home, backup_file, append_once, pkg_installed, command_exists |
| `lib/installer.sh` | Все функции безопасной установки: safe_download, safe_git_clone, install_oh_my_zsh_safe, install_k3s_safe, install_docker_compose_safe, install_neovim_safe, install_tailscale_safe, generate_random_password |
| `lib/profiles.sh` | apply_profile_workstation/ai_dev/full/cluster |
| `lib/bootstrap.sh` | Начальная инициализация, проверка переменных окружения |

---

## Идемпотентность

Каждый stage проверяет состояние **до** внесения изменений:

- `pkg_installed <name>` — проверка через `dpkg -s`
- `command_exists <cmd>` — проверка через `command -v`
- `is_done <stage>` — проверка маркера в `state/<stage>.done`
- `docker ps` — проверка запущенных контейнеров
- `nvcc --version` — проверка CUDA
- `tailscale status --self` — проверка Tailscale-авторизации

**Результат**: повторный запуск `pop-os-setup.sh` безвреден — уже установленные компоненты пропускаются.

---

## Безопасность (Hardening)

| Мера | Детали |
|------|--------|
| Никаких `curl \| sh` | Все загрузки → файл → проверка → установка |
| SHA256 verification | safe_download проверяет хеш каждого файла |
| Проверка зависимостей | require_cmd перед установкой |
| UFW default deny | Входящие заблокированы, исходящие разрешены |
| fail2ban | Бан SSH-атак после 3 попыток за 15 мин |
| sysctl hardening | kptr_restrict, dmesg_restrict, tcp_syncookies, rp_filter |
| unattended-upgrades | Автоматические патчи безопасности |
| SSH с ED25519 + passphrase | Ключи с защитой passphrase |
| Trap handlers | Корректная обработка INT/TERM/ERR |