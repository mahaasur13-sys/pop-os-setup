# Pop!_OS Setup — v3.0.0

> Modular auto-setup for Pop!_OS 24.04 LTS NVIDIA Edition — AI/Dev workstation

[![v3.0.0](https://img.shields.io/badge/version-3.0.0-blue.svg)](https://github.com/mahaasur13-sys/pop-os-setup)
[![shellcheck](https://github.com/mahaasur13-sys/pop-os-setup/actions/workflows/lint.yml/badge.svg)](https://github.com/mahaasur13-sys/pop-os-setup/actions)
[![Made for Pop!_OS](https://img.shields.io/badge/Pop!_OS-24.04%20LTS-red.svg)](https://pop.system76.com)

---

## Navigation

- [Quick Start](#-quick-start)
- [Architecture](#-architecture)
- [Profiles](#-profiles)
- [Stages](#-stages-126)
- [Security](#-security)
- [Makefile](#-makefile)
- [Troubleshooting](#-troubleshooting)

---

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/mahaasur13-sys/pop-os-setup.git
cd pop-os-setup

# Run (full setup, all stages)
sudo make run

# Run specific profile
sudo PROFILE=workstation make run

# Verify without running
make verify
```

### Requirements

- Pop!_OS 24.04 LTS (or Debian 12-based distro)
- NVIDIA GPU (optional — stages skip gracefully)
- Root/sudo access
- Internet connection

---

## 🏗 Architecture

```
pop-os-setup/
├── pop-os-setup.sh          # Main entry — sources lib/*.sh, runs selected profile
├── lib/
│   ├── logging.sh            # step(), ok(), warn(), err(), info(), log_sep()
│   ├── utils.sh             # get_target_user, get_user_home, pkg_installed,
│   │                         # ensure_dir, backup_file, append_once, apply_sysctl
│   ├── installer.sh          # safe_git_clone, safe_download, install_oh_my_zsh_safe,
│   │                         # install_neovim_safe, install_docker_compose_safe, etc.
│   └── profiles.sh           # Stage lists per profile (workstation/cluster/ai-dev/full)
├── stages/
│   ├── stage05_zsh.sh
│   ├── stage09_cuda.sh
│   ├── stage10_hardening.sh
│   ├── stage13_ollama.sh
│   ├── stage14_kubectl.sh
│   ├── stage17_docker_compose.sh
│   ├── stage19_monitoring.sh
│   ├── stage21_cron.sh
│   ├── stage22_neovim.sh
│   ├── stage23_notifications.sh
│   ├── stage24_ssh_gpg.sh
│   ├── stage25_backup.sh
│   └── stage26_final.sh
├── profiles/
│   ├── workstation.sh
│   ├── cluster.sh
│   ├── ai-dev.sh
│   └── full.sh
├── tests/integration/
│   ├── run.sh
│   ├── test-lib.sh
│   ├── test-stages.sh
│   ├── test-profiles.sh
│   └── test-cli.sh
└── Makefile
```

### Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Idempotency** | All stage functions safe to re-run; checks `! -f` before creating |
| **No curl\|sh** | All downloads go through `safe_download` → local file → execute |
| **No credentials in logs** | Passwords stored in `~/.config/pop-os-setup/`, never echo'd |
| **Defensive** | `set -euo pipefail` in scripts; `command_exists` / `pkg_installed` checks |
| **RCE-free** | No `eval`, no unquoted variables in command substitution |
| **Modular** | Each stage is independent; profiles compose stage subsets |

---

## 📦 Profiles

| Profile | Stages | Use case |
|---------|--------|----------|
| `workstation` | 5,7,8,10,17,21,22,23,24,25,26 | Desktop — KDE, Docker, Zsh, Neovim, SSH, backup |
| `cluster` | 10,14,15,16,17,18,19,20,21,26 | Home lab — k3s, Longhorn, Ceph, MetalLB |
| `ai-dev` | 5,7,8,9,10,12,13,17,21,22,23,25,26 | AI/ML — CUDA, Ollama, Jupyter, PyTorch |
| `full` | All stages | Everything |

---

## 📐 Stages 1–26

| # | Name | Key actions |
|---|------|-------------|
| 5 | Zsh + Oh My Zsh | install_oh_my_zsh_safe, plugins |
| 9 | CUDA Toolkit | nvidia-cuda-toolkit, driver check |
| 10 | System Hardening | UFW, fail2ban, sysctl, unattended-upgrades |
| 13 | Ollama | local LLM inference |
| 14 | kubectl + Helm | k8s tooling |
| 17 | Docker Compose | install_docker_compose_safe |
| 19 | Monitoring | Prometheus + Grafana + Loki |
| 21 | Cron Jobs | log cleanup, disk check, backup reminder |
| 22 | Neovim | install_neovim_safe + init.lua |
| 23 | Notifications | systemd user timers (GPU temp, updates) |
| 24 | SSH + GPG | ED25519 key with passphrase, gpg-agent, YubiKey |
| 25 | Backup & Recovery | Timeshift + rsync script + weekly schedule |
| 26 | Final Report | Service status, credentials summary, next steps |

---

## 🔐 Security

- **UFW** — default deny incoming, allow outgoing
- **fail2ban** — sshd jail (30min ban after 3 failures)
- **sysctl** — kptr_restrict, dmesg_restrict, tcp_syncookies, rp_filter
- **SSH keys** — ED25519 with passphrase (no empty -N), stored in `~/.ssh/`
- **No hardcoded credentials** — all generated via `generate_random_password`
- **safe_download** — SHA256 verification, retry logic, local execution
- **credential files** — `chmod 600`, stored in `~/.config/pop-os-setup/`

---

## 📋 Makefile

```bash
make help              # Show all targets
make verify            # Full check: lint + check-stages + security + docs
make lint              # bash -n + shellcheck -S warning
make check-stages      # Stage files + function definitions
make security-check    # Scan for RCE/credential patterns
make docs              # Validate documentation
make stage-list        # List all stage files with size
make integration-tests  # Run test suite
make run               # Execute pop-os-setup.sh as root
make clean             # Remove log files
```

---

## 🔧 Troubleshooting

```bash
# Re-run from specific stage
sudo bash pop-os-setup.sh --stage 10

# Check stage output
tail -50 /var/log/pop-os-setup.log

# Verify stage syntax
bash -n stages/stage10_hardening.sh

# Run integration tests
make integration-tests
```

---

## ⚠️ Failure Conditions

| Symptom | Action |
|---------|--------|
| `nvidia-smi` fails after stage 9 | Check Secure Boot, reinstall driver |
| k3s fails to start | Verify ports 6443, 2379-2380 are open |
| Ceph HEALTH_ERR | Do not proceed; fix storage first |
| Docker not running | `sudo systemctl enable --now docker` |

---

*pop-os-setup v3.0.0 — mahaasur13-sys / asurdev.zo.computer*
