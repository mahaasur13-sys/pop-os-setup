# Self-Hosted Runner Setup (без токенов / GitHub App)

## Быстрый старт (SSH-only)

```bash
# 1. На RTX head node:
mkdir -p actions-runner && cd actions-runner
curl -o actions-runner.tar.gz -L https://github.com/actions/runner/releases/download/v2.313.0/actions-runner-linux-x64-2.313.0.tar.gz
tar xzf actions-runner.tar.gz

# 2. Интерактивная настройка (скажет код и URL из GitHub Settings):
./config.sh --url https://github.com/mahaasur13-sys/home-cluster-iac --token <TOKEN_FROM_GITHUB>

# 3. Запуск как сервис:
./svc.sh install
./svc.sh start

# 4. Проверка:
./run.sh --status  # должен показать "Listening for Jobs"
```

## Деплой через SSH (без GitHub App)

После настройки раннера CI запускается через:

```bash
# Локальный запуск CI (без GitHub):
cd /path/to/home-cluster-iac
ansible-playbook -i ansible/inventory.ini ansible/playbook.yml \
  --tags "slurm_ha,k8s_federation" \
  --diff
```

## Обновление раннера

```bash
cd /home/ubuntu/actions-runner
./svc.sh stop
./bin/updaterewrapper.sh
./svc.sh start
```
