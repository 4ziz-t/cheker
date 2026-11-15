# Cheker

Мониторинг нод Remnawave и автоматическая смена IP доменов в Cloudflare при блокировке.

- Опрашивает ноды Remnawave. Если у ноды `isConnected` стал `false`, шлёт в Telegram «нода offline». Когда нода вернётся, шлёт «нода снова online» и сколько она не работала.
- По расписанию (по умолчанию раз в 15 минут) проверяет **все IP** каждого домена через cheburcheck.ru.
- Если **текущий** IP домена (A-запись) в бане, меняет A-запись на следующий доступный IP из списка этого домена: по порядку, по кругу. Шлёт уведомление в Telegram.
- Забаненные IP из списка не удаляются. Они перепроверяются каждый цикл, и после разбана IP снова становится доступным.
- IP можно сменить вручную из панели.
- Веб-панель на React (ПК и мобильная версия), тёмная тема, вход по паролю из `.env`.

## Структура

```
cheker/
├── backend/                 FastAPI
│   └── app/
│       ├── core/            конфиг, БД, сессии/пароль, время, http-клиент
│       ├── models/          SQLAlchemy-модели (SQLite)
│       ├── schemas/         Pydantic-схемы API
│       ├── checkers/        ИСТОЧНИКИ ПРОВЕРКИ IP (плагины)
│       │   ├── base.py          интерфейс BaseChecker
│       │   ├── registry.py      реестр
│       │   └── cheburcheck.py   cheburcheck.ru
│       ├── integrations/    Cloudflare, Remnawave, Telegram
│       ├── services/        бизнес-логика
│       │   ├── domain_service.py  проверка доменов и смена IP
│       │   ├── node_service.py    опрос нод
│       │   ├── scheduler.py       фоновые задачи
│       │   ├── events.py          журнал + уведомления
│       │   ├── summary.py         ежедневная сводка
│       │   └── settings_service.py настройки из фронта
│       ├── api/routes/      REST API
│       └── main.py
├── frontend/                React + Vite, чистый CSS (src/styles/*.css)
├── Dockerfile               собирает фронт и бекенд в один образ
├── docker-compose.yml       app + caddy
├── Caddyfile
└── .env.example
```

## Подготовка

1. **Cloudflare.** My Profile → API Tokens → Create Token → Custom token. Нужны права:
   `Zone → Zone → Read` и `Zone → DNS → Edit` для нужных зон.
   Proxy (оранжевое облако) у A-записей должен быть выключен. Cheker его не трогает и при смене IP сохраняет текущее значение.
2. **Remnawave.** В панели: Настройки → API Tokens → создать токен. Нужны URL панели и токен.
3. **Telegram.** Создайте бота у @BotFather и напишите ему `/start`. Свой `chat_id` можно узнать у @userinfobot.
4. Домен для самой панели Cheker (например `cheker.example.com`): A-запись на IP VPS.

> Сервер с Cheker лучше держать **вне РФ**: из РФ запросы к Cloudflare API и Telegram сами могут упереться в блокировки.

## Запуск на VPS

```bash
git clone <repo> cheker && cd cheker      # или скопируйте папку
cp .env.example .env
nano .env                                  # заполните пароль, домен и токены
docker compose up -d --build
docker compose logs -f app
```

Панель откроется на `https://PANEL_DOMAIN`.

**Если на сервере уже работает Caddy или nginx** (например, на сервере с панелью Remnawave), порты 80/443 заняты. Тогда:
- удалите сервис `caddy` из `docker-compose.yml`;
- у `app` замените `expose` на `ports: ["127.0.0.1:8000:8000"]`;
- в существующий Caddyfile добавьте:
  ```
  cheker.example.com {
      reverse_proxy 127.0.0.1:8000
  }
  ```

Данные (SQLite) лежат в `./data/cheker.db`. Для бэкапа достаточно копировать эту папку.

### Обновление

```bash
docker compose up -d --build
```

## Как это работает

### Цикл проверки доменов
Для каждого включённого домена:
1. Читается A-запись из Cloudflare. Если её изменили вручную в Cloudflare, Cheker это заметит и пришлёт уведомление «A-запись изменена вне панели».
2. Через все включённые источники проверяются все IP из списка домена. Один IP проверяется один раз за цикл, даже если он есть в нескольких доменах.
3. Если текущий IP в бане и автосмена включена (у домена и глобально), выбирается следующий IP после текущего со статусом «доступен». Порядок — как в списке, по кругу. A-запись меняется в Cloudflare.
4. Если доступных IP нет, приходит одно уведомление «Нет доступных IP». Повторно оно придёт только после того, как ситуация хоть раз исправится.
5. Если у домена нет A-записи, она создаётся с первым доступным IP.

IP считается заблокированным, если **хотя бы один** источник вернул `blocked: true`. Если источник не ответил, автосмена не происходит: статус «Ошибка», плюс одно уведомление об ошибке и одно о восстановлении.

### Уведомления в Telegram
Бан IP, разбан IP, автосмена, ручная смена, нет доступных IP, изменение A-записи вне панели, нода offline/online, ошибки API (Cloudflare, Remnawave, чекеры), блокировка входа при подборе пароля, ежедневная сводка. Каждое событие включается и выключается в Настройках.

### Защита входа
- Пароль из `APP_PASSWORD` (4–6 латинских букв/цифр).
- 5 неверных попыток с одного IP за 15 минут блокируют этот IP на 15 минут.
- 30 неверных попыток за час со всех IP включают глобальную блокировку на 30 минут (защита от перебора с разных адресов) и шлют уведомление в Telegram.
- Сессия хранится 7 дней в httpOnly-cookie.

## Как добавить новый источник проверки IP

1. Создайте `backend/app/checkers/my_source.py`:

```python
from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker


@register_checker
class MySourceChecker(BaseChecker):
    name = "my_source"                 # уникальный id
    title = "Мой источник"             # название во фронте
    description = "Что проверяет"
    enabled_by_default = False

    async def check(self, ip: str) -> CheckResult:
        resp = await self.client.get("https://example.com/api", params={"ip": ip})
        if resp.status_code != 200:
            return CheckResult(self.name, None, error=f"HTTP {resp.status_code}")
        data = resp.json()
        return CheckResult(self.name, blocked=bool(data["blocked"]), details={"raw": data})
```

2. Добавьте импорт в `backend/app/checkers/__init__.py`:

```python
from app.checkers import cheburcheck, my_source  # noqa: F401
```

3. Пересоберите контейнер. Источник появится в разделе «Настройки → Источники проверки IP».

## Локальная разработка

```bash
# бекенд
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # COOKIE_SECURE=false
uvicorn app.main:app --reload

# фронтенд (в другом терминале)
cd frontend
npm install
npm run dev               # http://localhost:5173, /api проксируется на :8000
```

## API (коротко)

| Метод | Путь | Что делает |
|---|---|---|
| POST | `/api/auth/login` | вход |
| GET | `/api/dashboard` | сводка для дашборда |
| GET/POST | `/api/domains` | список / создание домена |
| GET/PATCH/DELETE | `/api/domains/{id}` | домен |
| PUT | `/api/domains/{id}/ips` | заменить список IP (порядок важен) |
| POST | `/api/domains/{id}/switch` | ручная смена IP `{ "ip": "1.2.3.4" }` |
| POST | `/api/domains/{id}/check` | проверить домен сейчас |
| GET | `/api/nodes` | ноды |
| POST | `/api/nodes/{uuid}/restart\|enable\|disable` | действия с нодой |
| GET | `/api/events` | журнал событий |
| GET/PUT | `/api/settings` | настройки |
| POST | `/api/system/check-now` | запустить полную проверку |
| GET | `/api/tools/check-ip?ip=` | проверить любой IP |
