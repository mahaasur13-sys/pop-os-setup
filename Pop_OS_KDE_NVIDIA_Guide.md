# Pop!_OS 24.04 NVIDIA Edition + KDE Plasma: Гайд для новичков

## Описание
Данный гайд охватывает установку KDE Plasma поверх Pop!_OS 24.04 NVIDIA Edition — от подготовки загрузочной флешки до тонкой настройки.

---

## Содержание (навигация)

1. [Что такое Pop!_OS и почему KDE](#1-что-такое-popos-и-почему-kde)
2. [Подготовка к установке](#2-подготовка-к-установке)
3. [Установка Pop!_OS 24.04 NVIDIA Edition](#3-установка-popos-2404-nvidia-edition)
4. [Первоначальная настройка после установки](#4-первоначальная-настройка-после-установки)
5. [Установка KDE Plasma](#5-установка-kde-plasma)
6. [Настройка NVIDIA и Wayland](#6-настройка-nvidia-и-wayland)
7. [Оптимизация и полезные советы](#7-оптимизация-и-полезные-советы)
8. [Устранение неполадок](#8-устранение-неполадок)

---

## 1. Что такое Pop!_OS и почему KDE

### 1.1 Что такое Pop!_OS?

**Pop!_OS** — это дистрибутив Linux на базе Ubuntu, разработанный компанией System76.

| Характеристика | Описание |
|----------------|----------|
| **NVIDIA Edition** | Поставляется с предустановленными проприетарными драйверами NVIDIA |
| **CUDA/ROCm** | Оптимизирован для вычислений на GPU |
| **LTS** | Длительная поддержка — 4 года |
| **Ядро** | Based on Ubuntu 24.04 LTS |

### 1.2 Почему KDE Plasma?

- **Гибкость** — Полная кастомизация интерфейса
- **Производительность** — Легковеснее, чем GNOME (по умолчанию в Pop!_OS)
- **Привычность** — Схожесть с Windows для пользователей, переходящих с Windows
- **Функциональность** — Встроенные функции: файловый менеджер, терминал, системные настройки

---

## 2. Подготовка к установке

### 2.1 Системные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| CPU | 2 ядра | 4+ ядра |
| RAM | 4 GB | 8+ GB |
| Диск | 50 GB | 100+ GB SSD |
| GPU | NVIDIA с поддержкой | NVIDIA RTX / GTX 1000+ |

### 2.2 Что подготовить

1. **Загрузочная флешка** — минимум 8 GB
2. **Скачать образ**: [Pop!_OS 24.04 NVIDIA Edition](https://pop.system76.com)
3. **Средство записи**: Balena Etcher, Rufus или dd

### 2.3 Скачивание и проверка образа

```bash
# Проверка контрольной суммы SHA256
sha256sum pop-os_24.04_amd64_nvidia_6.iso
```

### 2.4 Создание загрузочной флешки

**Windows (Rufus):**
1. Скачать Rufus с https://rufus.ie
2. Выбрать USB-устройство
3. Указать ISO-файл
4. Выбрать схему разделов "GPT"
5. Нажать "Старт"

**Linux (dd):**
```bash
sudo dd if=pop-os_24.04_amd64_nvidia_6.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

> ⚠️ Замените `/dev/sdX` на реальное имя вашего USB-устройства (например, `/dev/sdb`)

---

## 3. Установка Pop!_OS 24.04 NVIDIA Edition

### 3.1 Загрузка с флешки

1. Вставить флешку и включить компьютер
2. Войти в BIOS/UEFI (обычно **F2**, **F12**, **Del** или **Esc**)
3. Изменить порядок загрузки: **USB First**
4. Сохранить и перезагрузиться

### 3.2 Пошаговая установка

#### Шаг 1: Выбор языка
- Выбрать **English** (рекомендуется для корректной работы установщика)
- Или выбрать **Русский** для локализованной установки

#### Шаг 2: Раскладка клавиатуры
- Выбрать нужную раскладку (по умолчанию English US)
- Можно добавить дополнительные (Russian, Ukrainian)

#### Шаг 3: Тип установки

| Тип | Описание | Риск |
|-----|----------|------|
| **Erase Disk and Install** | Полное удаление данных и установка | Высокий |
| **Custom Mounting** | Ручная разметка диска | Для опытных |
| **Encrypt Drive** | Шифрование всего диска | Замедляет работу |

> **Рекомендация для новичков**: Выбрать "Erase Disk and Install"

#### Шаг 4: Разметка диска (для продвинутых)

```
/boot/efi   512 MB   EFI System Partition
/           50-100 GB Ext4
/home       остаток  Ext4 (рекомендуется вынести отдельно)
swap        8-16 GB  (если спящий режим не нужен — можно пропустить)
```

#### Шаг 5: Создание пользователя
- **Имя пользователя**: латиницей (например, `alex`)
- **Имя компьютера**: (например, `pop-desktop`)
- **Пароль**: надёжный, минимум 8 символов

#### Шаг 6: Завершение установки
- Дождаться завершения (**10-20 минут**)
- Перезагрузить систему
- Извлечь флешку

---

## 4. Первоначальная настройка после установки

### 4.1 Первый вход в систему

После загрузки появится экран входа Pop!_OS (GNOME по умолчанию). Войдите под созданным пользователем.

### 4.2 Обновление системы

```bash
# Открыть терминал (Ctrl + Alt + T)
sudo apt update && sudo apt upgrade -y
```

### 4.3 Проверка NVIDIA драйверов

```bash
# Проверить версию драйвера
nvidia-smi

# Проверить загруженный модуль ядра
lsmod | grep nvidia
```

**Ожидаемый вывод `nvidia-smi`:**
```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 550.x.x       Driver Version: 550.x.x       CUDA Version: 12.4 |
|-------------------------------+----------------------+----------------------+
| GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
|===============================+======================+======================|
|   0  NVIDIA GeForce ...    Off | 00000000:01:00.0  On |                  N/A |
+-------------------------------+----------------------+----------------------+
```

---

## 5. Установка KDE Plasma

### 5.1 Два варианта установки

| Вариант | Команда | Размер | Описание |
|---------|---------|--------|----------|
| **Минимальная** | `kde-plasma-desktop` | ~1 GB | Только KDE, без лишних приложений |
| **Полная** | `kde-full` | ~3 GB | KDE + набор приложений KDE |

### 5.2 Установка минимального KDE Plasma

```bash
sudo apt install kde-plasma-desktop sddm
```

### 5.3 Установка полного набора KDE Apps

```bash
sudo apt install kde-full sddm
```

### 5.4 Выбор SDDM в качестве менеджера входа

```bash
# Интерактивный выбор
sudo dpkg-reconfigure sddm

# Или вручную
sudo update-alternatives --config x-session-manager
```

### 5.5 Перезагрузка

```bash
sudo reboot
```

### 5.6 Выбор KDE Plasma при входе

1. На экране входа **SDDM** нажать на шестерёнку/меню
2. Выбрать **Plasma (X11)** или **Plasma (Wayland)**
3. Ввести пароль и войти

> 💡 **Рекомендация**: Для NVIDIA-карт начните с **Plasma (X11)** — более стабильный.

---

## 6. Настройка NVIDIA и Wayland

### 6.1 Проверка текущего режима

```bash
echo $XDG_SESSION_TYPE
```

- `x11` — используется X11
- `wayland` — используется Wayland

### 6.2 Включение Wayland для NVIDIA

Wayland работает с NVIDIA, но требует дополнительных настроек.

#### Способ 1: Через настройки SDDM

```bash
sudo nano /etc/sddm.conf
```

Добавить:
```ini
[Wayland]
Session=/usr/share/wayland-sessions/plasma.desktop
```

#### Способ 2: Через Plasma настройки

1. Открыть **System Settings** → **Display and Monitor** → **Compositor**
2. Включить/выключить Wayland по необходимости

### 6.3 Настройка NVIDIA PRIME

Для переключения между NVIDIA и встроенной графикой:

```bash
# Проверить доступные профили
sudo prime-select query

# Переключить на NVIDIA (максимальная производительность)
sudo prime-select nvidia

# Переключить на Intel/AMD встроенную (экономия энергии)
sudo prime-select intel

# Вернуть режим On-Demand
sudo prime-select on-demand

# Применить изменения
sudo reboot
```

### 6.4 Управление питанием (для ноутбуков)

```bash
# Или использовать системные настройки Plasma
# System Settings → Power Management → Energy Savings
```

### 6.5 Оптимизация производительности NVIDIA

```bash
sudo nano /etc/X11/xorg.conf.d/20-nvidia.conf
```

Добавить:
```ini
Section "Device"
    Identifier "NVIDIA Card"
    Driver "nvidia"
    Option "TripleBuffer" "True"
    Option "ForceFullCompositionPipeline" "True"
EndSection
```

> ⚠️ Эти опции увеличивают энергопотребление, но улучшают плавность.

---

## 7. Оптимизация и полезные советы

### 7.1 Установка дополнительных приложений

#### Мультимедиа
```bash
sudo apt install vlc ffmpeg gstreamer1.0-plugins-good
```

#### Архиваторы
```bash
sudo apt install ark p7zip-full unzip
```

#### Сетевые инструменты
```bash
sudo apt install network-manager-openvpn network-manager-vpnc
```

### 7.2 Оптимизация KDE Plasma

#### Ускорение анимации
1. **System Settings** → **Workspace** → **Workspace Behavior** → **General Behavior**
2. Установить "Instant" для всех анимаций

#### Отключение эффектов (слабое железо)
1. **System Settings** → **Display and Monitor** → **Compositor**
2. Отключить "Enable compositor on output"

### 7.3 Установка Latte Dock (альтернативная панель)

```bash
sudo apt install latte-dock
```

### 7.4 Полезные горячие клавиши KDE

| Комбинация | Действие |
|------------|----------|
| `Alt + Space` | KRunner (быстрый запуск) |
| `Alt + Tab` | Переключение окон |
| `Meta (Win)` | Меню приложений |
| `Ctrl + Alt + L` | Блокировка экрана |
| `Print Screen` | Снимок экрана |

---

## 8. Устранение неполадок

### 8.1 Чёрный экран после установки KDE

**Проблема**: После перезагрузки чёрный экран.

**Решение**:
1. Переключиться на tty: `Ctrl + Alt + F2`
2. Войти под своим пользователем
3. Переустановить драйверы NVIDIA:
```bash
sudo apt install --reinstall nvidia-driver-550
sudo reboot
```

### 8.2 SDDM не загружается

**Проблема**: Экран входа не появляется.

**Решение**:
```bash
# Переключиться на GDM
sudo dpkg-reconfigure gdm3

# Или переустановить SDDM
sudo apt install --reinstall sddm
sudo reboot
```

### 8.3 NVIDIA PRIME не работает

**Проблема**: Невозможно переключить профиль.

**Решение**:
```bash
# Вручную переключить
sudo tee /sys/module/nvidia_drm/parameters/modeset=1
sudo prime-select nvidia
sudo reboot
```

### 8.4 Wayland глючит с NVIDIA

**Проблема**: Зависания, артефакты в Wayland.

**Решение**:
1. Вернуться на X11 (Plasma X11 session)
2. Или обновить драйвер:
```bash
sudo apt update && sudo apt install nvidia-driver-555
```

### 8.5 KDE вылетает после входа

**Проблема**: Краш после ввода пароля.

**Решение**:
1. Войти в консоль: `Ctrl + Alt + F2`
2. Удалить настройки KDE:
```bash
rm -rf ~/.config/plasma*
rm -rf ~/.config/kwin*
```

### 8.6 Низкая производительность GPU

**Проверка:**
```bash
# Запустить тест
glxgears -info

# Проверить частоты
nvidia-smi -q -i 0 | grep -A 3 "Clocks"
```

---

## Краткая шпаргалка команд

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Информация о NVIDIA
nvidia-smi

# Версия драйвера
cat /proc/driver/nvidia/version

# Переключение профиля
sudo prime-select nvidia|intel|on-demand

# Перезагрузка
sudo reboot

# Вход в консоль
Ctrl + Alt + F2

# Выход из KDE
killall plasma-desktop
```

---

## Дополнительные ресурсы

- [Документация Pop!_OS](https://pop.planined.com/docs/)
- [Arch Wiki: NVIDIA](https://wiki.archlinux.org/title/NVIDIA)
- [KDE UserBase Wiki](https://userbase.kde.org/)
- [System76 Support](https://support.system76.com/)

---

*Гайд подготовлен в April 2026.*
