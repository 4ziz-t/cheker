#!/usr/bin/env bash
# Установка Cheker одной командой:
#   bash <(curl -fsSL https://raw.githubusercontent.com/4ziz-t/cheker/main/install.sh)
#
# Что делает:
#   1. ставит git, curl и Docker (если их нет);
#   2. скачивает Cheker из GitHub в /opt/cheker (или обновляет, если уже скачан);
#   3. спрашивает домен панели и пароль, создаёт .env;
#   4. собирает и запускает контейнеры (backend, frontend, Caddy с HTTPS).
#
# Повторный запуск — обновление: код подтянется из GitHub, настройки (.env и база) останутся.
#
# Переменные (необязательно):
#   CHEKER_DIR=/opt/cheker   куда ставить
#   CHEKER_REPO=…            адрес репозитория (для приватного: https://<токен>@github.com/…)
#   CHEKER_BRANCH=main       ветка
set -euo pipefail

REPO="${CHEKER_REPO:-https://github.com/4ziz-t/cheker.git}"
BRANCH="${CHEKER_BRANCH:-main}"
DIR="${CHEKER_DIR:-/opt/cheker}"

c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_dim=$'\e[2m'; c_b=$'\e[1m'; c_0=$'\e[0m'
say()  { printf '%s\n' "${c_b}▸${c_0} $*"; }
ok()   { printf '%s\n' "${c_ok}✔${c_0} $*"; }
warn() { printf '%s\n' "${c_warn}!${c_0} $*"; }
die()  { printf '%s\n' "${c_err}✖ $*${c_0}" >&2; exit 1; }

# ввод всегда с терминала — скрипт может прийти через curl | bash
ask() {  # ask "Вопрос" [по умолчанию] → в REPLY
  local q="$1" def="${2:-}"
  if [[ -n "$def" ]]; then q="$q ${c_dim}[$def]${c_0}"; fi
  read -r -p "$q: " REPLY </dev/tty || die "Нет терминала для ввода — запустите команду в интерактивной SSH-сессии"
  REPLY="${REPLY:-$def}"
}

[[ $EUID -eq 0 ]] || die "Запустите от root (или через sudo)"
[[ -r /dev/tty ]] || die "Нужен интерактивный терминал"

echo
printf '%s\n' "${c_b}Cheker — установка${c_0}"
echo

# ---------- 1. зависимости ----------
install_pkg() {
  if command -v apt-get >/dev/null; then
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" >/dev/null
  elif command -v dnf >/dev/null; then
    dnf install -y -q "$@" >/dev/null
  elif command -v yum >/dev/null; then
    yum install -y -q "$@" >/dev/null
  else
    die "Не знаю, как установить $* на этой системе — поставьте вручную"
  fi
}

for bin in git curl; do
  if ! command -v "$bin" >/dev/null; then
    say "Ставлю $bin…"
    install_pkg "$bin"
  fi
done

if ! command -v docker >/dev/null; then
  say "Ставлю Docker (get.docker.com)…"
  curl -fsSL https://get.docker.com | sh >/dev/null
  systemctl enable --now docker >/dev/null 2>&1 || true
fi
docker compose version >/dev/null 2>&1 || die "Нет плагина docker compose — обновите Docker (https://docs.docker.com/engine/install/)"
ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '')"

# ---------- 2. код ----------
if [[ -d "$DIR/.git" ]]; then
  say "Cheker уже есть в $DIR — обновляю из GitHub…"
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" checkout -q "$BRANCH"
  git -C "$DIR" reset -q --hard "origin/$BRANCH"
  UPDATE=1
else
  [[ -e "$DIR" && -n "$(ls -A "$DIR" 2>/dev/null)" ]] && die "$DIR уже существует и не пуст — укажите другую папку: CHEKER_DIR=/путь"
  say "Скачиваю Cheker в $DIR…"
  git clone -q --branch "$BRANCH" "$REPO" "$DIR" \
    || die "Не удалось скачать $REPO. Если репозиторий приватный: CHEKER_REPO=https://<токен>@github.com/4ziz-t/cheker.git"
  UPDATE=0
fi
cd "$DIR"
ok "Код: $(git log -1 --format='%h %cd' --date=short)"

# ---------- 3. настройки ----------
set_env() {  # set_env КЛЮЧ ЗНАЧЕНИЕ — заменить или добавить строку в .env
  local key="$1" val="$2"
  if grep -q "^${key}=" .env; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' .env >"$tmp" && mv "$tmp" .env
  else
    printf '%s=%s\n' "$key" "$val" >>.env
  fi
}

configure=1
if [[ -f .env ]]; then
  current_domain="$(grep -E '^PANEL_DOMAIN=' .env | cut -d= -f2- || true)"
  ask "Найден .env (домен: ${current_domain:-не задан}). Оставить настройки как есть? [Y/n]" "Y"
  [[ "$REPLY" =~ ^[Nn] ]] || configure=0
fi

if [[ $configure -eq 1 ]]; then
  # домен
  while true; do
    ask "Домен панели (например, cheker.example.com)"
    DOMAIN="$(echo "$REPLY" | tr 'A-Z' 'a-z' | sed -E 's#^https?://##; s#/.*$##')"
    [[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] && break
    warn "Похоже, это не домен. Пример: cheker.example.com"
  done

  # пароль: 4–6 латинских букв/цифр
  while true; do
    read -r -s -p "Пароль для входа (4–6 латинских букв и/или цифр): " PASS </dev/tty; echo
    if [[ ! "$PASS" =~ ^[A-Za-z0-9]{4,6}$ ]]; then warn "Нужно 4–6 символов: только латинские буквы и цифры"; continue; fi
    read -r -s -p "Повторите пароль: " PASS2 </dev/tty; echo
    [[ "$PASS" == "$PASS2" ]] && break
    warn "Пароли не совпали, ещё раз"
  done

  ask "Часовой пояс (для ежедневного отчёта)" "Europe/Moscow"
  TZ_VALUE="$REPLY"

  [[ -f .env ]] && cp .env ".env.bak.$(date +%Y%m%d%H%M%S)"
  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then cp .env.example .env; else : >.env; fi
  fi
  set_env APP_PASSWORD "$PASS"
  set_env PANEL_DOMAIN "$DOMAIN"
  set_env TZ "$TZ_VALUE"
  set_env COOKIE_SECURE true
  chmod 600 .env
  ok "Создан .env (токены Remnawave, Cloudflare, Telegram и др. — потом в панели: «Настройки → Интеграции»)"
else
  DOMAIN="$(grep -E '^PANEL_DOMAIN=' .env | cut -d= -f2-)"
fi

# ---------- проверки перед запуском ----------
PUBLIC_IP="$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
DOMAIN_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
if [[ -n "$PUBLIC_IP" && -n "$DOMAIN_IP" && "$PUBLIC_IP" != "$DOMAIN_IP" ]]; then
  warn "A-запись $DOMAIN указывает на $DOMAIN_IP, а у этого сервера IP $PUBLIC_IP."
  warn "HTTPS-сертификат не выпустится, пока A-запись не укажет на этот сервер (в Cloudflare — серое облако)."
elif [[ -z "$DOMAIN_IP" ]]; then
  warn "Домен $DOMAIN пока не резолвится. Создайте A-запись на ${PUBLIC_IP:-IP этого сервера} — Caddy выпустит сертификат сам."
fi

if command -v ss >/dev/null; then
  busy="$(ss -ltnH '( sport = :80 or sport = :443 )' 2>/dev/null | grep -v docker-proxy || true)"
  if [[ -n "$busy" ]] && ! docker ps --format '{{.Names}}' | grep -q '^cheker-caddy$'; then
    warn "Порты 80/443 уже заняты другой программой (nginx, apache…). Caddy не сможет запуститься, пока их не освободить."
  fi
fi

# ---------- 4. запуск ----------
mkdir -p data
say "Собираю и запускаю контейнеры (первый раз — несколько минут)…"
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null 2>&1 || true

say "Жду, пока backend запустится…"
for _ in $(seq 1 30); do
  state="$(docker inspect -f '{{.State.Health.Status}}' cheker-backend 2>/dev/null || echo starting)"
  [[ "$state" == "healthy" ]] && break
  sleep 3
done
if [[ "${state:-}" == "healthy" ]]; then ok "Backend работает"; else warn "Backend ещё запускается — проверьте: docker compose -f $DIR/docker-compose.yml logs backend"; fi

echo
ok "${c_b}Cheker $( [[ $UPDATE -eq 1 ]] && echo 'обновлён' || echo 'установлен' )${c_0}"
echo "   Панель:      https://$DOMAIN"
echo "   Папка:       $DIR  (база — $DIR/data)"
echo "   Логи:        cd $DIR && docker compose logs -f backend"
echo "   Обновить:    снова запустите эту же команду установки"
echo "   Остановить:  cd $DIR && docker compose down"
echo
