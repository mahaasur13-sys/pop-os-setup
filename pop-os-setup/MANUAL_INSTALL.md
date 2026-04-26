# Ручная установка компонентов (без pop-os-setup)

> Для тех, кто хочет установить только нужные компоненты или уже имеет часть окружения.
> ver: v12.0 | совместимость: Pop!_OS 24.04 / Ubuntu 24.04

---

## 📊 Обзор системы — что устанавливает pop-os-setup

Система состоит из **26 стадий** (stage01 → stage26), которые покрывают всё: от базовых dev tools до кластерного HPC-software.

| Стадия | Название | Категория | Критичность | Профили |
|--------|----------|-----------|-------------|---------|
| 01 | Preflight / Pre-install check | System | REQUIRED | all |
| 02–08 | Auto-repair stages | System | REQUIRED | all |
| 05 | Zsh + Oh My Zsh | Dev Tools | REQUIRED | all |
| 06 | KDE Plasma Desktop | Desktop | OPTIONAL | workstation |
| 07 | Docker Engine | Containers | REQUIRED | workstation, full, cluster |
| 08 | Python + AI Tools (Jupyter, Ollama, Pyenv) | AI Stack | REQUIRED | ai-dev, full |
| 09 | CUDA Toolkit 12.4 + cuDNN | AI Stack | OPTIONAL | ai-dev, full |
| 10 | UFW + fail2ban + sysctl hardening | Security | REQUIRED | all |
| 12 | Kernel tuning (I/O scheduler, hugepages, earlyoom) | System | REQUIRED | all |
| 13 | Tailscale VPN | System | REQUIRED | full, cluster |
| 14 | k3s Kubernetes | Containers | REQUIRED | full, cluster |
| 15 | Slurm (HPC workload manager) | System | OPTIONAL | cluster |
| 16 | CPU + NVIDIA power tuning (TLP) | System | OPTIONAL | all |
| 17 | Docker Compose v2 | Containers | REQUIRED | workstation, full |
| 19 | Prometheus + Grafana | System | OPTIONAL | full, workstation |
| 22 | Neovim (latest AppImage) | Dev Tools | REQUIRED | all |
| 23 | Уведомления (libnotify, ntfy) | System | OPTIONAL | all |
| 24 | SSH Server + GPG Agent | Security | OPTIONAL | all |
| 25 | BorgBackup | System | OPTIONAL | full |

---

## 📋 Профиль → Компоненты (матрица)

| Компонент | workstation | ai-dev | full | cluster |
|-----------|:-----------:|:------:|:----:|:-------:|
| Dev Tools (build-essential, git, curl...) | ✅ | ✅ | ✅ | ✅ |
| Zsh + Oh My Zsh | ✅ | ✅ | ✅ | ✅ |
| Neovim | ✅ | ✅ | ✅ | ✅ |
| Docker Engine | ✅ | ✅ | ✅ | ✅ |
| Docker Compose | ✅ | ✅ | ✅ | ✅ |
| Python + Jupyter + Ollama | — | ✅ | ✅ | ✅ |
| CUDA 12.4 + cuDNN | — | ✅ | ✅ | — |
| Tailscale VPN | — | — | ✅ | ✅ |
| k3s Kubernetes | — | — | ✅ | ✅ |
| Slurm (HPC) | — | — | — | ✅ |
| KDE Plasma | ✅ | — | — | — |
| Prometheus + Grafana | ✅ | — | ✅ | — |
| UFW + fail2ban | ✅ | ✅ | ✅ | ✅ |
| Kernel tuning | ✅ | ✅ | ✅ | ✅ |
| CPU/NVIDIA power (TLP) | ✅ | ✅ | ✅ | ✅ |
| BorgBackup | — | — | ✅ | — |
| SSH + GPG | — | — | ✅ | ✅ |
| Notifications (ntfy) | — | — | ✅ | ✅ |

---

## 🧱 Постадийное описание компонентов

### Stage 01 — Preflight (Проверка окружения)

- **Что это:** скрипт предварительной проверки перед установкой
- **Зачем:** убедиться что система готова — enough RAM, disk space, Pop!_OS/Ubuntu 24.04
- **Даёт:** безопасность от установки на несовместимое окружение
- **Критичность:** REQUIRED

---

### Stage 05 — Zsh + Oh My Zsh

- **Что это:** современный Zsh shell с фреймворком Oh My Zsh и плагинами
- **Зачем:** удобный shell с автодополнением, подсветкой синтаксиса, git-алиасами
- **Даёт:** быстрая навигация, продуктивность в терминале
- **Критичность:** REQUIRED
- **Профиль:** all

```bash
sudo apt install -y zsh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
git clone https://github.com/zsh-users/zsh-syntax-highlighting.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting
```

---

### Stage 06 — KDE Plasma Desktop

- **Что это:** полноценный Linux-десктоп (KDE Plasma)
- **Зачем:** замена GNOME на Pop!_OS, выбор между Wayland и X11 сессиями
- **Даёт:** альтернативное окружение рабочего стола
- **Критичность:** OPTIONAL
- **Профиль:** workstation

```bash
sudo apt install -y kde-plasma-desktop  # полная установка
sudo systemctl enable sddm
```

---

### Stage 07 — Docker Engine

- **Что это:** контейнеризация — Docker CE с плагинами (buildx, compose)
- **Зачем:** запуск контейнеров, DevOps, изоляция сервисов
- **Даёт:** docker run/pull/build, docker compose, управление образами
- **Критичность:** REQUIRED
- **Профиль:** workstation, full, cluster

```bash
# Безопасная установка (без pipe | sh)
sudo apt remove -y docker docker-engine docker.io containerd runc
sudo apt install -y ca-certificates curl gnupg lsb-release
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
sudo systemctl enable docker
```

---

### Stage 08 — Python + AI Tools (Jupyter, Ollama, Pyenv)

- **Что это:** Python 3 + pip + venv + Jupyter Notebook + Ollama (локальные LLM) + Pyenv
- **Зачем:** разработка AI/ML, Jupyter Notebook для экспериментов, локальные языковые модели
- **Даёт:** python3, jupyter notebook, ollama (LLaMA, Mistral, etc локально), pyenv (управление версиями Python)
- **Критичность:** REQUIRED
- **Профиль:** ai-dev, full

```bash
sudo apt install -y python3 python3-pip python3-venv python3-full
pip3 install jupyter notebook
curl -fsSL https://ollama.com/install.sh | sh
curl -fsSL https://pyenv.run | bash
```

---

### Stage 09 — CUDA Toolkit 12.4 + cuDNN

- **Что это:** NVIDIA CUDA 12.4 + cuDNN для GPU-ускорения ML
- **Зачем:** запуск PyTorch/TensorFlow на GPU NVIDIA, training и inference
- **Даёт:** nvidia-smi, nvcc, CUDA libraries, cuDNN для deep learning
- **Критичность:** OPTIONAL (требует NVIDIA GPU)
- **Профиль:** ai-dev, full

```bash
sudo apt install -y gnupg2
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/3bf863cc.pub | \
    sudo gpg --dearmor -o /etc/apt/keyrings/nvidia-drivers.gpg
echo "deb [signed-by=/etc/apt/keyrings/nvidia-drivers.gpg] https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/ cuda-12-4" | \
    sudo tee /etc/apt/sources.list.d/cuda.list
sudo apt update
sudo apt install -y cuda-toolkit-12-4 libcudnn9 libcudnn9-dev
```

---

### Stage 10 — UFW + fail2ban + sysctl (Hardening)

- **Что это:** firewall (UFW), защита от brute-force (fail2ban), kernel hardening (sysctl)
- **Зачем:** безопасность системы — блокировка неавторизованного доступа, защита от атак
- **Даёт:** настроенный firewall с правилами, блокировка SSH-брутфорса, hardened kernel params
- **Критичность:** REQUIRED
- **Профиль:** all

```bash
sudo apt install -y ufw fail2ban
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.0.0/16 to any port 22 proto tcp comment 'SSH-local'
sudo ufw allow from 10.0.0.0/8 to any port 22 proto tcp comment 'SSH-Tailscale'
sudo ufw enable
sudo tee /etc/fail2ban/jail.local > /dev/null << 'EOF'
[sshd]
enabled = true
port = 22
maxretry = 3
bantime = 1800
findtime = 600
EOF
sudo tee /etc/sysctl.d/99-security.conf > /dev/null << 'EOF'
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.yama.ptrace_scope = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
EOF
sudo sysctl --system
```

---

### Stage 12 — Kernel Tuning (Оптимизация ядра)

- **Что это:** I/O scheduler, transparent hugepages, earlyoom, swappiness, file descriptors
- **Зачем:** оптимизация производительности дисков и памяти, предотвращение OOM
- **Даёт:** mq-deadline scheduler, transparent hugepages, earlyoom (мониторинг RAM), настроенные лимиты
- **Критичность:** REQUIRED
- **Профиль:** all

```bash
echo 'ACTION=="add|change", KERNEL=="sd*" ATTR{queue/scheduler}="mq-deadline"' | \
    sudo tee /etc/udev/rules.d/60-io-scheduler.rules
echo 'always' | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo 'always' | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
sudo apt install -y earlyoom
sudo systemctl enable earlyoom
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
echo '* soft nofile 1048576' | sudo tee -a /etc/security/limits.conf
echo '* hard nofile 1048576' | sudo tee -a /etc/security/limits.conf
```

---

### Stage 13 — Tailscale VPN

- **Что это:** Tailscale VPN ( WireGuard-based, без портов/настройки )
- **Зачем:** безопасный доступ к кластеру из любой точки, without configuring port forwarding/NAT
- **Даёт:** tailscale up, private network, SSH из любой точки, доступ к сервисам
- **Критичность:** REQUIRED
- **Профиль:** full, cluster

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --operator=$USER
```

---

### Stage 14 — k3s Kubernetes

- **Что это:** легковесный Kubernetes (k3s) — master или agent
- **Зачем:** оркестрация контейнеров, управление кластером, декларативный deployment
- **Даёт:** kubectl, k3s API, service mesh, pods/services/deployments
- **Критичность:** REQUIRED
- **Профиль:** full, cluster

```bash
# Master
curl -sfL https://get.k3s.io | sh -
# Agent
curl -sfL https://get.k3s.io | K3S_URL=https://<MASTER_IP>:6443 K3S_TOKEN=<TOKEN> sh -
kubectl get nodes
```

---

### Stage 15 — Slurm (HPC Workload Manager)

- **Что это:** Slurm — система управления HPC-кластером (jobs, queues, resourse allocation)
- **Зачем:** планирование GPU/CPU jobs на нескольких узлах, HPC workloads
- **Даёт:** slurmctld, slurmd, munge, squeue, sbatch
- **Критичность:** OPTIONAL
- **Профиль:** cluster

```bash
sudo apt install -y munge munge-libs libmunge-dev slurm-wlm slurmctld slurmd
sudo create-munge-key -r
sudo chmod 400 /etc/munge/munge.key
```

---

### Stage 16 — CPU + NVIDIA Power Tuning (TLP)

- **Что это:** TLP (CPU power management), NVIDIA persistence mode, CPU governor
- **Зачем:** энергоэффективность, управление питанием, снижение energy consumption
- **Даёт:** автоматическое управление CPU governor, NVIDIA persistence, power saving
- **Критичность:** OPTIONAL
- **Профиль:** all

```bash
sudo apt install -y tlp tlp-rdw
sudo systemctl enable tlp
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo 'powersave' | sudo tee $cpu
done
sudo nvidia-smi -pm 1
sudo nvidia-smi -pl <WATTAGE>
```

---

### Stage 17 — Docker Compose v2

- **Что это:** Docker Compose plugin (встроен в Docker CE) + standalone docker-compose-switch
- **Зачем:** multi-container приложения (docker-compose.yml),定义的服层
- **Даёт:** docker compose up/down, multi-service orchestration
- **Критичность:** REQUIRED
- **Профиль:** workstation, full

```bash
docker compose version  # уже установлен с Docker
sudo apt install -y docker-compose-switch  # переключение версий
```

---

### Stage 19 — Prometheus + Grafana (Мониторинг)

- **Что это:** Prometheus (metrics collection) + Grafana (визуализация) + Node Exporter
- **Зачем:** мониторинг системы, метрики CPU/RAM/disk/network, визуальные дашборды
- **Даёт:** prometheus server, grafana dashboards, node_exporter (per-host metrics)
- **Критичность:** OPTIONAL
- **Профиль:** full, workstation

```bash
sudo apt install -y prometheus prometheus-node-exporter grafana
sudo systemctl enable prometheus grafana-server
```

---

### Stage 22 — Neovim (Latest AppImage)

- **Что это:** современный текстовый редактор (Neovim AppImage latest)
- **Зачем:** замена vim, IDE для разработки, Lua config, plugins
- **Даёт:** nvim, init.lua config, LSP support
- **Критичность:** REQUIRED
- **Профиль:** all

```bash
curl -LO https://github.com/neovim/neovim/releases/latest/download/nvim.appimage
chmod +x nvim.appimage
sudo mv nvim.appimage /usr/local/bin/nvim
```

---

### Stage 23 — Notifications (Уведомления)

- **Что это:** libnotify-bin (нативные уведомления) + ntfy (HTTP push)
- **Зачем:** отправка уведомлений о результатах установки, CI/CD alerts
- **Даёт:** notify-send, ntfy send, Telegram-бот
- **Критичность:** OPTIONAL
- **Профиль:** all

```bash
sudo apt install -y libnotify-bin ntfy
notify-send "Установка завершена" "Все компоненты настроены"
```

---

### Stage 24 — SSH Server + GPG Agent

- **Что это:** OpenSSH server + GPG agent + SSH forwarding
- **Зачем:** удалённый доступ по SSH, GPG key management, SSH agent forwarding
- **Даёт:** sshd, gpg-agent, secure remote access
- **Критичность:** OPTIONAL
- **Профиль:** full

```bash
sudo apt install -y openssh-server
sudo tee /etc/ssh/sshd_config.d/hardened.conf > /dev/null << 'EOF'
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 2
ClientAliveInterval 300
EOF
sudo apt install -y gnupg2
```

---

### Stage 25 — BorgBackup

- **Что это:** BorgBackup — deduplicating backup (эффективное хранение бэкапов)
- **Зачем:** бэкап системы, encrypted backups, deduplication
- **Даёт:** borg create/extract, encrypted remote backups
- **Критичность:** OPTIONAL
- **Профиль:** full

```bash
sudo apt install -y borgbackup
borg init --encryption=repokey borg@<BACKUP_HOST>:/path/to/repo
```

---

## 📌 Перед началом

```bash
# Обнови систему
sudo apt update && sudo apt upgrade -y

# Перезагрузись после обновления ядра
sudo systemctl reboot
```

---

## 🔧 Базовые Dev Tools

### Stage 04 — Dev Tools (базовый набор)

```bash
sudo apt install -y \
    build-essential git curl wget vim htop ncdu tree jq \
    gdisk smartmontools lsof iotop strace file
```

---

## 🐚 Zsh + Oh My Zsh

### Stage 05 — Zsh + Oh My Zsh

```bash
# Установка Zsh
sudo apt install -y zsh

# Установка Oh My Zsh (безопасный способ — без pipe)
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended

# Плагины
git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
git clone https://github.com/zsh-users/zsh-syntax-highlighting.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting

# Добавь в ~/.zshrc:
# plugins=(git docker ansible zsh-autosuggestions zsh-syntax-highlighting)
```

---

## 🐳 Docker

### Stage 07 — Docker Engine

```bash
# Удаление старой версии
sudo apt remove -y docker docker-engine docker.io containerd runc

# Установка зависимостей
sudo apt install -y ca-certificates curl gnupg lsb-release

# Добавление GPG-ключа Docker
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Репозиторий
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установка
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Добавление пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker

# Автозапуск
sudo systemctl enable docker
sudo systemctl start docker
```

---

## 🐍 Python + AI Tools

### Stage 08 — Python + Jupyter + Ollama

```bash
# Python 3 + pip + venv
sudo apt install -y python3 python3-pip python3-venv python3-full

# Jupyter Notebook
pip3 install jupyter notebook

# Ollama (локальные LLM)
curl -fsSL https://ollama.com/install.sh | sh

# Pyenv (управление версиями Python)
curl -fsSL https://pyenv.run | bash

# Добавь в ~/.bashrc:
# export PATH="$HOME/.pyenv/bin:$PATH"
# eval "$(pyenv init --path)"
# eval "$(pyenv init -)"
```

---

## 🎮 CUDA Toolkit + cuDNN

### Stage 09 — CUDA 12.4 + cuDNN

> ⚠️ Требует NVIDIA GPU и установленные драйверы.

```bash
# Проверка драйвера
nvidia-smi

# Установка CUDA keyring (безопасный способ)
sudo apt install -y gnupg2
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/3bf863cc.pub | \
    sudo gpg --dearmor -o /etc/apt/keyrings/nvidia-drivers.gpg

# CUDA 12.4 repository
echo "deb [signed-by=/etc/apt/keyrings/nvidia-drivers.gpg] https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/ cuda-12-4" | \
    sudo tee /etc/apt/sources.list.d/cuda.list

sudo apt update
sudo apt install -y cuda-toolkit-12-4

# cuDNN
sudo apt install -y libcudnn9 libcudnn9-dev

# Настройка PATH
echo 'export PATH=/usr/local/cuda-12.4/bin:$PATH' | sudo tee /etc/profile.d/cuda.sh
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.4/lib64:$LD_LIBRARY_PATH' | sudo tee -a /etc/profile.d/cuda.sh
source /etc/profile.d/cuda.sh
```

---

## 🔒 Hardening (Безопасность)

### Stage 10 — UFW + fail2ban + sysctl

```bash
# UFW firewall
sudo apt install -y ufw

sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow out 53/udp comment 'DNS'

# SSH-доступ только из локальной сети
sudo ufw allow from 192.168.0.0/16 to any port 22 proto tcp comment 'SSH-local'
sudo ufw allow from 10.0.0.0/8 to any port 22 proto tcp comment 'SSH-Tailscale'
sudo ufw enable

# fail2ban
sudo apt install -y fail2ban

sudo tee /etc/fail2ban/jail.local > /dev/null << 'EOF'
[sshd]
enabled = true
port = 22
maxretry = 3
bantime = 1800
findtime = 600
EOF

sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# sysctl hardening
sudo tee /etc/sysctl.d/99-security.conf > /dev/null << 'EOF'
# Kernel pointers visibility
kernel.kptr_restrict = 2
# Restrict dmesg
kernel.dmesg_restrict = 1
# Ptrace scope
kernel.yama.ptrace_scope = 1
# TCP SYN cookies
net.ipv4.tcp_syncookies = 1
# Disable source packet routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
# Disable ICMP redirects
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
# Log martians
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
EOF

sudo sysctl --system
```

---

## 🚀 Docker Compose

### Stage 17 — Docker Compose v2

```bash
# Уже входит в docker-compose-plugin (см. Docker выше)
# Проверка:
docker compose version

# Или standalone (альтернатива):
sudo apt install -y docker-compose

# docker-compose-switch (переключение версий)
sudo apt install -y docker-compose-switch
```

---

## 📦 Kubernetes (k3s)

### Stage 14 — k3s

```bash
# Master-нода:
curl -sfL https://get.k3s.io | sh -

# Agent-нода (добавление к кластеру):
curl -sfL https://get.k3s.io | K3S_URL=https://<MASTER_IP>:6443 K3S_TOKEN=<TOKEN> sh -

# Проверка:
kubectl get nodes
sudo systemctl status k3s
```

---

## ⚙️ System Optimization

### Stage 12 — Оптимизация ядра

```bash
# I/O scheduler
echo 'BLOCKDEVICE=$(findmnt / -o source -n | sed "s/[0-9]//g")' | sudo tee /etc/default/sys-tuning
echo 'ACTION=="add|change", KERNEL=="sd*" ATTR{queue/scheduler}="mq-deadline"' | \
    sudo tee /etc/udev/rules.d/60-io-scheduler.rules

# Transparent Hugepages
echo 'always' | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo 'always' | sudo tee /sys/kernel/mm/transparent_hugepage/defrag

# earlyoom
sudo apt install -y earlyoom
sudo systemctl enable earlyoom
sudo systemctl start earlyoom

# swappiness
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf

# Файловые дескрипторы
echo '* soft nofile 1048576' | sudo tee -a /etc/security/limits.conf
echo '* hard nofile 1048576' | sudo tee -a /etc/security/limits.conf
```

---

## 🔑 SSH + GPG

### Stage 24 — SSH Server + GPG Agent

```bash
# OpenSSH server
sudo apt install -y openssh-server

# Конфиг sshd
sudo tee /etc/ssh/sshd_config.d/hardened.conf > /dev/null << 'EOF'
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 2
ClientAliveInterval 300
EOF

sudo systemctl enable sshd
sudo systemctl start sshd
sudo ufw allow 22/tcp

# GPG agent + SSH forwarding
sudo apt install -y gnupg2

tee ~/.gnupg/gpg-agent.conf > /dev/null << 'EOF'
allow-loopback-pinentry
enable-putty-support
EOF

# Добавить в ~/.bashrc / ~/.zshrc:
# export GPG_TTY=$(tty)
# export SSH_AUTH_SOCK=$(gpgconf --list-options gpg-agent 2>/dev/null | grep -oP '(?<=socket-dir=)\K[^ ]+/[^ ]+')
# gpg-connect-agent /bye > /dev/null
```

---

## 🌐 Tailscale

### Stage 13 — Tailscale VPN

```bash
# Установка
curl -fsSL https://tailscale.com/install.sh | sh

# Авторизация (one-line)
sudo tailscale up --operator=$USER

# Проверка
tailscale status
tailscale ip -4
```

---

## 💻 KDE Plasma

### Stage 06 — KDE Plasma Desktop

```bash
# Полная установка KDE
sudo apt install -y kde-plasma-desktop

# Только базовые компоненты
sudo apt install -y plasma-desktop

# Выбор сессии при входе: Plasma (Wayland или X11)

# Автозапуск SDDM
sudo systemctl enable sddm
```

---

## 📊 Мониторинг

### Stage 19 — Prometheus + Grafana

```bash
# Prometheus
sudo apt install -y prometheus

# Node Exporter
sudo apt install -y prometheus-node-exporter

# Grafana
sudo apt install -y grafana

sudo systemctl enable prometheus
sudo systemctl enable grafana-server
sudo systemctl start prometheus
sudo systemctl start grafana-server
```

---

## ⚡ Power Tuning

### Stage 16 — CPU + NVIDIA Power

```bash
# TLP (управление питанием)
sudo apt install -y tlp tlp-rdw

sudo systemctl enable tlp
sudo systemctl start tlp

# CPU governor
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo 'powersave' | sudo tee $cpu
done

# NVIDIA persistence mode
sudo nvidia-smi -pm 1
sudo nvidia-smi -pl <WATTAGE>
```

---

## 📸 Backup (BorgBackup)

### Stage 25 — BorgBackup

```bash
sudo apt install -y borgbackup

# Инициализация репозитория
borg init --encryption=repokey borg@<BACKUP_HOST>:/path/to/repo

# Пример backup script (добавь в cron)
# borg create --compression lz4 \
#     borg@<HOST>:/backups::{hostname}-{now:%Y-%m-%d} \
#     /etc /home/$USER --exclude '*/.cache'

# Восстановление
# borg extract borg@<HOST>:/backups::latest
```

---

## 🧬 Slurm

### Stage 15 — Slurm (HPC)

```bash
# Munge (аутентификация)
sudo apt install -y munge munge-libs libmunge-dev slurm-wlm slurmctld slurmd

# Генерация munge key
sudo create-munge-key -r
sudo chmod 400 /etc/munge/munge.key

# Конфиг
sudo tee /etc/slurm-llnl/slurm.conf > /dev/null << 'EOF'
SlurmctldHost=$(hostname)
ClusterName=cluster
SlurmUser=slurm
GresTypes=gpu
NodeName=localhost NodeAddr=127.0.0.1 State=UNKNOWN
PartitionName=debug Nodes=localhost Default=YES MaxTime=INFINITE State=UP
EOF

sudo systemctl enable munge
sudo systemctl enable slurmctld
sudo systemctl start munge
sudo systemctl start slurmctld
```

---

## 🔔 Notifications

### Stage 23 — Уведомления

```bash
# libnotify (нативные уведомления)
sudo apt install -y libnotify-bin

# ntfy (HTTP-уведомления)
sudo apt install -y ntfy

# Пример отправки:
notify-send "Установка завершена" "Все компоненты настроены"
ntfy send "Сервер готов"

# Telegram (через бота):
# curl -s -X POST https://api.telegram.org/bot<TOKEN>/sendMessage \
#     -d chat_id=<CHAT_ID> -d text="Установка завершена"
```

---

## 🛞 Neovim

### Stage 22 — Neovim (Latest AppImage)

```bash
# AppImage
curl -LO https://github.com/neovim/neovim/releases/latest/download/nvim.appimage
chmod +x nvim.appimage
sudo mv nvim.appimage /usr/local/bin/nvim

# Или из apt:
sudo apt install -y neovim

# Конфигурация
mkdir -p ~/.config/nvim
tee ~/.config/nvim/init.lua > /dev/null << 'EOF'
-- Minimal config
vim.opt.number = true
vim.opt.relativenumber = true
vim.opt.expandtab = true
vim.opt.tabstop = 4
vim.opt.shiftwidth = 4
vim.opt.termguicolors = true
vim.opt.termguicolors = true
vim.cmd [[colorscheme ron]]
EOF
```

---

## 📋 Итоговая сводка

| Компонент | Stage | Категория | Критичность | Профиль |
|-----------|-------|-----------|-------------|---------|
| Dev Tools | 04 | Dev Tools | REQUIRED | all |
| Zsh + OMZ | 05 | Dev Tools | REQUIRED | all |
| Neovim | 22 | Dev Tools | REQUIRED | all |
| Docker Engine | 07 | Containers | REQUIRED | workstation, full, cluster |
| Docker Compose | 17 | Containers | REQUIRED | workstation, full |
| Python + AI | 08 | AI Stack | REQUIRED | ai-dev, full |
| CUDA 12.4 + cuDNN | 09 | AI Stack | OPTIONAL | ai-dev, full |
| k3s Kubernetes | 14 | Containers | REQUIRED | full, cluster |
| Tailscale VPN | 13 | System | REQUIRED | full, cluster |
| UFW + fail2ban | 10 | Security | REQUIRED | all |
| Kernel tuning | 12 | System | REQUIRED | all |
| CPU/NVIDIA power (TLP) | 16 | System | OPTIONAL | all |
| KDE Plasma | 06 | Desktop | OPTIONAL | workstation |
| Prometheus + Grafana | 19 | System | OPTIONAL | full, workstation |
| Slurm (HPC) | 15 | System | OPTIONAL | cluster |
| BorgBackup | 25 | System | OPTIONAL | full |
| SSH + GPG | 24 | Security | OPTIONAL | full |
| Notifications | 23 | System | OPTIONAL | all |