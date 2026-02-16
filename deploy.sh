#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Daily Analyst — Server Deployment Script
# Полное развёртывание Telegram AI-бота на VPS (Ubuntu/Debian)
#
# Использование:
#   chmod +x deploy.sh
#   ./deploy.sh setup        — первичная настройка сервера
#   ./deploy.sh deploy       — сборка и запуск
#   ./deploy.sh ssl          — получение SSL-сертификата
#   ./deploy.sh update       — обновление из git + перезапуск
#   ./deploy.sh logs         — просмотр логов бота
#   ./deploy.sh status       — статус всех контейнеров
#   ./deploy.sh backup       — резервная копия данных
#   ./deploy.sh restore      — восстановление из бекапа
#   ./deploy.sh stop         — остановка всех контейнеров
#   ./deploy.sh restart      — перезапуск всех контейнеров
#   ./deploy.sh health       — проверка здоровья
#   ./deploy.sh cleanup      — очистка старых Docker-образов
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Цвета для вывода ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
log_error() { echo -e "${RED}[✗]${NC} $*"; }
log_step()  { echo -e "${BLUE}[→]${NC} $*"; }
log_header(){ echo -e "\n${CYAN}═══ $* ═══${NC}\n"; }

# ── Базовая директория ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_NAME="daily-analyst"
BACKUP_DIR="$SCRIPT_DIR/backups"

# ── Вспомогательные функции ───────────────────────────────────────────────────

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Этот скрипт нужно запускать с sudo для первичной настройки"
        log_info "Для deploy/update/logs sudo не нужен"
        exit 1
    fi
}

check_env_file() {
    if [[ ! -f .env ]]; then
        log_error "Файл .env не найден!"
        log_step "Создаю из шаблона..."
        cp .env.example .env
        log_warn "ОБЯЗАТЕЛЬНО отредактируй .env перед запуском:"
        log_warn "  nano .env"
        exit 1
    fi
}

load_env() {
    check_env_file
    set -a
    source .env
    set +a
}

check_docker() {
    if ! command -v docker &>/dev/null; then
        log_error "Docker не установлен. Запусти: ./deploy.sh setup"
        exit 1
    fi
    if ! docker compose version &>/dev/null; then
        log_error "Docker Compose V2 не установлен. Запусти: ./deploy.sh setup"
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# SETUP — первичная настройка сервера
# ═══════════════════════════════════════════════════════════════════════════════

cmd_setup() {
    log_header "Первичная настройка сервера"
    check_root

    # 1. Обновление системы
    log_step "Обновляю систему..."
    apt-get update -qq
    apt-get upgrade -y -qq

    # 2. Установка необходимых пакетов
    log_step "Устанавливаю зависимости..."
    apt-get install -y -qq \
        ca-certificates curl gnupg lsb-release \
        git ufw fail2ban htop

    # 3. Установка Docker
    if ! command -v docker &>/dev/null; then
        log_step "Устанавливаю Docker..."
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
            gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg

        echo \
            "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
            https://download.docker.com/linux/ubuntu \
            $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
            tee /etc/apt/sources.list.d/docker.list > /dev/null

        apt-get update -qq
        apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
        log_info "Docker установлен"
    else
        log_info "Docker уже установлен: $(docker --version)"
    fi

    # 4. Добавить текущего пользователя в группу docker
    REAL_USER="${SUDO_USER:-$USER}"
    if [[ "$REAL_USER" != "root" ]]; then
        usermod -aG docker "$REAL_USER"
        log_info "Пользователь $REAL_USER добавлен в группу docker"
    fi

    # 5. Настройка файрвола
    log_step "Настраиваю файрвол (UFW)..."
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
    log_info "Файрвол настроен: SSH + HTTP + HTTPS"

    # 6. Настройка fail2ban
    log_step "Настраиваю fail2ban..."
    systemctl enable fail2ban
    systemctl start fail2ban
    log_info "fail2ban активирован"

    # 7. Включить Docker автозапуск
    systemctl enable docker
    systemctl start docker

    # 8. Создать .env если нет
    if [[ ! -f .env ]]; then
        cp .env.example .env
        log_warn "Создан .env из шаблона. ОБЯЗАТЕЛЬНО заполни:"
        log_warn "  nano $SCRIPT_DIR/.env"
    fi

    # 9. Создать директорию для бекапов
    mkdir -p "$BACKUP_DIR"

    echo ""
    log_info "Настройка завершена!"
    echo ""
    log_step "Следующие шаги:"
    echo "  1. Отредактируй .env:  nano .env"
    echo "  2. Получи SSL:         ./deploy.sh ssl"
    echo "  3. Запусти бота:       ./deploy.sh deploy"
    echo ""
    if [[ "$REAL_USER" != "root" ]]; then
        log_warn "Перелогинься чтобы применить группу docker:"
        log_warn "  exit && ssh $REAL_USER@<server>"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# SSL — получение Let's Encrypt сертификата
# ═══════════════════════════════════════════════════════════════════════════════

cmd_ssl() {
    log_header "Получение SSL-сертификата"
    load_env
    check_docker

    if [[ -z "${DOMAIN:-}" ]]; then
        log_error "DOMAIN не указан в .env"
        exit 1
    fi

    log_step "Домен: $DOMAIN"

    # Создать директории для certbot
    mkdir -p nginx/certbot/conf nginx/certbot/www

    # Проверить, есть ли уже сертификат
    if [[ -d "nginx/certbot/conf/live/$DOMAIN" ]]; then
        log_warn "Сертификат уже существует. Обновляю..."
        docker compose run --rm certbot renew
        docker compose exec nginx nginx -s reload 2>/dev/null || true
        log_info "Сертификат обновлён"
        return
    fi

    # Временная nginx-конфигурация только для HTTP (ACME challenge)
    log_step "Запускаю временный nginx для ACME challenge..."

    # Создаем временный nginx конфиг
    cat > nginx/nginx-temp.conf <<TEMPCONF
events { worker_connections 128; }
http {
    server {
        listen 80;
        server_name $DOMAIN;
        location /.well-known/acme-challenge/ { root /var/www/certbot; }
        location / { return 200 'ok'; add_header Content-Type text/plain; }
    }
}
TEMPCONF

    # Запускаем временный nginx
    docker run -d --name temp-nginx \
        -p 80:80 \
        -v "$SCRIPT_DIR/nginx/nginx-temp.conf:/etc/nginx/nginx.conf:ro" \
        -v "$SCRIPT_DIR/nginx/certbot/www:/var/www/certbot" \
        nginx:alpine

    sleep 3

    # Запрашиваем сертификат
    log_step "Запрашиваю сертификат у Let's Encrypt..."
    docker run --rm \
        -v "$SCRIPT_DIR/nginx/certbot/conf:/etc/letsencrypt" \
        -v "$SCRIPT_DIR/nginx/certbot/www:/var/www/certbot" \
        certbot/certbot certonly \
            --webroot \
            --webroot-path=/var/www/certbot \
            --email "admin@$DOMAIN" \
            --agree-tos \
            --no-eff-email \
            -d "$DOMAIN"

    # Убираем временный nginx
    docker stop temp-nginx && docker rm temp-nginx
    rm -f nginx/nginx-temp.conf

    if [[ -d "nginx/certbot/conf/live/$DOMAIN" ]]; then
        log_info "SSL-сертификат получен для $DOMAIN"
    else
        log_error "Не удалось получить сертификат. Проверь:"
        log_error "  1. DNS A-запись $DOMAIN → IP сервера"
        log_error "  2. Порт 80 открыт"
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# DEPLOY — сборка и запуск
# ═══════════════════════════════════════════════════════════════════════════════

cmd_deploy() {
    log_header "Развёртывание $PROJECT_NAME"
    load_env
    check_docker

    # Проверка обязательных переменных
    local required_vars=("TELEGRAM_BOT_TOKEN" "OPENAI_API_KEY" "NOTION_TOKEN" "NOTION_DATABASE_ID")
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]] || [[ "${!var}" == *"your_"* ]] || [[ "${!var}" == *"_here"* ]]; then
            log_error "$var не настроен в .env"
            exit 1
        fi
    done

    # Проверка SSL для production
    if [[ -n "${DOMAIN:-}" ]] && [[ ! -d "nginx/certbot/conf/live/$DOMAIN" ]]; then
        log_warn "SSL-сертификат не найден для $DOMAIN"
        log_warn "Запусти: ./deploy.sh ssl"
        log_warn "Запускаю только бота без nginx..."
        docker compose up -d bot
    else
        log_step "Сборка Docker-образа..."
        docker compose build --no-cache

        log_step "Запуск контейнеров..."
        docker compose up -d

        log_info "Все контейнеры запущены"
    fi

    # Ждем старта
    log_step "Ожидаю готовности бота..."
    sleep 5
    cmd_health_quiet && log_info "Бот работает!" || log_warn "Бот ещё запускается, проверь: ./deploy.sh health"

    echo ""
    log_step "Полезные команды:"
    echo "  ./deploy.sh logs     — логи"
    echo "  ./deploy.sh status   — статус"
    echo "  ./deploy.sh health   — проверка"
}

# ═══════════════════════════════════════════════════════════════════════════════
# UPDATE — обновление из git + перезапуск
# ═══════════════════════════════════════════════════════════════════════════════

cmd_update() {
    log_header "Обновление $PROJECT_NAME"
    check_docker

    # Бекап перед обновлением
    log_step "Создаю бекап перед обновлением..."
    cmd_backup_quiet

    # Pull из git
    if [[ -d .git ]]; then
        log_step "Обновляю код из git..."
        git pull --rebase
    else
        log_warn "Не git-репозиторий, пропускаю git pull"
    fi

    # Пересборка и перезапуск
    log_step "Пересобираю Docker-образ..."
    docker compose build

    log_step "Перезапуск контейнеров (zero-downtime)..."
    docker compose up -d --remove-orphans

    sleep 5
    cmd_health_quiet && log_info "Обновление завершено!" || log_warn "Проверь: ./deploy.sh health"
}

# ═══════════════════════════════════════════════════════════════════════════════
# LOGS — просмотр логов
# ═══════════════════════════════════════════════════════════════════════════════

cmd_logs() {
    check_docker
    local service="${1:-bot}"
    local lines="${2:-100}"
    docker compose logs -f --tail="$lines" "$service"
}

# ═══════════════════════════════════════════════════════════════════════════════
# STATUS — статус контейнеров
# ═══════════════════════════════════════════════════════════════════════════════

cmd_status() {
    log_header "Статус контейнеров"
    check_docker
    docker compose ps -a
    echo ""
    log_step "Использование ресурсов:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" \
        $(docker compose ps -q 2>/dev/null) 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH — проверка здоровья
# ═══════════════════════════════════════════════════════════════════════════════

cmd_health_quiet() {
    local port="${APP_PORT:-8000}"
    local response
    response=$(curl -sf "http://localhost:$port/health" 2>/dev/null) || return 1
    echo "$response" | grep -q '"status":"ok"' 2>/dev/null
}

cmd_health() {
    log_header "Проверка здоровья"
    load_env

    local port="${APP_PORT:-8000}"
    log_step "Проверяю http://localhost:$port/health ..."

    local response
    if response=$(curl -sf "http://localhost:$port/health" 2>/dev/null); then
        log_info "Бот: OK — $response"
    else
        log_error "Бот: НЕ ОТВЕЧАЕТ"
        log_step "Логи последних 20 строк:"
        docker compose logs --tail=20 bot 2>/dev/null || true
    fi

    # Проверка nginx если есть домен
    if [[ -n "${DOMAIN:-}" ]]; then
        if curl -sf "https://$DOMAIN/health" -o /dev/null 2>/dev/null; then
            log_info "Nginx + SSL: OK"
        else
            if curl -sf "http://$DOMAIN/health" -o /dev/null 2>/dev/null; then
                log_warn "Nginx: OK, но SSL не работает"
            else
                log_error "Nginx: НЕ ОТВЕЧАЕТ"
            fi
        fi
    fi

    # Docker health
    log_step "Docker контейнеры:"
    docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP — резервная копия данных
# ═══════════════════════════════════════════════════════════════════════════════

cmd_backup_quiet() {
    mkdir -p "$BACKUP_DIR"
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/backup_${ts}.tar.gz"

    # Копируем данные из Docker volume
    local container_id
    container_id=$(docker compose ps -q bot 2>/dev/null || echo "")

    if [[ -n "$container_id" ]]; then
        docker cp "$container_id:/app/data" "$BACKUP_DIR/data_tmp" 2>/dev/null || true
    fi

    # Архивируем
    tar -czf "$backup_file" \
        -C "$SCRIPT_DIR" .env \
        -C "$BACKUP_DIR" data_tmp 2>/dev/null || \
    tar -czf "$backup_file" -C "$SCRIPT_DIR" .env 2>/dev/null || true

    rm -rf "$BACKUP_DIR/data_tmp"

    # Удаляем бекапы старше 30 дней
    find "$BACKUP_DIR" -name "backup_*.tar.gz" -mtime +30 -delete 2>/dev/null || true
}

cmd_backup() {
    log_header "Резервное копирование"
    cmd_backup_quiet
    log_info "Бекап создан в $BACKUP_DIR/"
    ls -lh "$BACKUP_DIR"/backup_*.tar.gz 2>/dev/null | tail -5
}

# ═══════════════════════════════════════════════════════════════════════════════
# RESTORE — восстановление из бекапа
# ═══════════════════════════════════════════════════════════════════════════════

cmd_restore() {
    log_header "Восстановление из бекапа"

    local backup_file="${1:-}"
    if [[ -z "$backup_file" ]]; then
        log_step "Доступные бекапы:"
        ls -lh "$BACKUP_DIR"/backup_*.tar.gz 2>/dev/null || { log_error "Бекапов нет"; exit 1; }
        echo ""
        log_error "Укажи файл бекапа: ./deploy.sh restore backups/backup_20250101_120000.tar.gz"
        exit 1
    fi

    if [[ ! -f "$backup_file" ]]; then
        log_error "Файл не найден: $backup_file"
        exit 1
    fi

    log_warn "Это восстановит данные из бекапа. Продолжить? (y/N)"
    read -r confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_info "Отменено"
        exit 0
    fi

    log_step "Останавливаю контейнеры..."
    docker compose down

    log_step "Восстанавливаю данные..."
    tar -xzf "$backup_file" -C /tmp/restore_tmp 2>/dev/null || true

    if [[ -f /tmp/restore_tmp/.env ]]; then
        cp /tmp/restore_tmp/.env "$SCRIPT_DIR/.env"
        log_info ".env восстановлен"
    fi

    rm -rf /tmp/restore_tmp

    log_step "Запускаю контейнеры..."
    cmd_deploy
}

# ═══════════════════════════════════════════════════════════════════════════════
# STOP / RESTART
# ═══════════════════════════════════════════════════════════════════════════════

cmd_stop() {
    log_header "Остановка контейнеров"
    check_docker
    docker compose down
    log_info "Все контейнеры остановлены"
}

cmd_restart() {
    log_header "Перезапуск контейнеров"
    check_docker
    docker compose restart
    sleep 5
    cmd_health_quiet && log_info "Перезапуск завершён, бот работает" || log_warn "Проверь: ./deploy.sh health"
}

# ═══════════════════════════════════════════════════════════════════════════════
# CLEANUP — очистка старых Docker-образов
# ═══════════════════════════════════════════════════════════════════════════════

cmd_cleanup() {
    log_header "Очистка Docker"
    check_docker
    log_step "Удаляю неиспользуемые образы и контейнеры..."
    docker system prune -f
    log_info "Очистка завершена"
    docker system df
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

usage() {
    echo -e "${CYAN}Daily Analyst — Deployment Script${NC}"
    echo ""
    echo "Использование: ./deploy.sh <команда>"
    echo ""
    echo "Команды:"
    echo "  setup      Первичная настройка сервера (нужен sudo)"
    echo "  ssl        Получение SSL-сертификата Let's Encrypt"
    echo "  deploy     Сборка и запуск всех контейнеров"
    echo "  update     Обновление из git + перезапуск"
    echo "  logs       Просмотр логов (по умолчанию: bot)"
    echo "  status     Статус контейнеров и ресурсов"
    echo "  health     Проверка здоровья приложения"
    echo "  backup     Резервная копия данных"
    echo "  restore    Восстановление из бекапа"
    echo "  stop       Остановка всех контейнеров"
    echo "  restart    Перезапуск всех контейнеров"
    echo "  cleanup    Очистка старых Docker-образов"
    echo ""
    echo "Примеры:"
    echo "  sudo ./deploy.sh setup        # первый раз на новом сервере"
    echo "  ./deploy.sh ssl               # получить SSL"
    echo "  ./deploy.sh deploy            # запустить бота"
    echo "  ./deploy.sh logs bot 200      # последние 200 строк логов"
    echo "  ./deploy.sh update            # обновить и перезапустить"
}

case "${1:-}" in
    setup)   cmd_setup   ;;
    ssl)     cmd_ssl     ;;
    deploy)  cmd_deploy  ;;
    update)  cmd_update  ;;
    logs)    cmd_logs "${2:-bot}" "${3:-100}" ;;
    status)  cmd_status  ;;
    health)  cmd_health  ;;
    backup)  cmd_backup  ;;
    restore) cmd_restore "${2:-}" ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    cleanup) cmd_cleanup ;;
    *)       usage       ;;
esac
