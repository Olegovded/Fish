# Деплой на VPS (круглосуточная работа)

Инструкция поднимает бота **@Ribakru_bot** на дешёвом VPS так, чтобы он работал
постоянно и сам перезапускался после падений и перезагрузок сервера.

Подойдёт самый маленький тариф (1 vCPU / 1 ГБ, ~200–400 ₽/мес) любого
провайдера с Ubuntu/Debian. Все команды — под `root` или через `sudo`.

---

## 0. Что понадобится

- VPS с Ubuntu 22.04/24.04 (или Debian 12) и доступом по SSH.
- Токен бота от @BotFather (уже есть) и username бота (`Ribakru_bot`).
- **Важно:** на VPS должен быть открыт доступ к `api.telegram.org` (у обычных
  зарубежных VPS он открыт; у некоторых российских — может быть заблокирован,
  тогда нужен VPS с зарубежной локацией или прокси).

---

## 1. Установить систему и создать пользователя

```bash
apt update && apt install -y python3-venv git
# отдельный пользователь без прав root — так безопаснее
adduser --system --group --home /opt/fishing-bot fishbot
```

## 2. Забрать код

```bash
cd /opt/fishing-bot
sudo -u fishbot git clone <URL-вашего-репозитория> .
sudo -u fishbot git checkout claude/telegram-fishing-bot-mvp-27rotr
```

## 3. Поставить зависимости

```bash
sudo -u fishbot python3 -m venv .venv
sudo -u fishbot .venv/bin/pip install -r requirements.txt
```

## 4. Создать `.env` с секретами

Файл `.env` НЕ хранится в git — создаём его вручную на сервере:

```bash
sudo -u fishbot tee /opt/fishing-bot/.env >/dev/null <<'EOF'
BOT_TOKEN=ВСТАВЬТЕ_СЮДА_ТОКЕН_ОТ_BOTFATHER
BOT_USERNAME=Ribakru_bot
DB_PATH=/opt/fishing-bot/fishing.db
GRID_SIZE_M=1000
WEBAPP_URL=
WEB_HOST=0.0.0.0
WEB_PORT=8080
EOF
chmod 600 /opt/fishing-bot/.env
chown fishbot:fishbot /opt/fishing-bot/.env
```

> Если перевыпустите токен у @BotFather — поменяйте только строку `BOT_TOKEN`
> и перезапустите сервис (`systemctl restart fishing-bot`).

## 5. Установить systemd-сервис

Подставляем в шаблон путь и пользователя и копируем в systemd:

```bash
sed -e 's#__APPDIR__#/opt/fishing-bot#g' \
    -e 's#__USER__#fishbot#g' \
    /opt/fishing-bot/deploy/fishing-bot.service \
    > /etc/systemd/system/fishing-bot.service

systemctl daemon-reload
systemctl enable --now fishing-bot
```

## 6. Проверить

```bash
systemctl status fishing-bot        # должно быть active (running)
journalctl -u fishing-bot -f        # живой лог; ждём строку «Бот запущен»
```

Теперь откройте в Telegram **@Ribakru_bot**, нажмите `/start` — пойдёт сценарий
отчёта.

---

## Обновление кода (когда добавим функции)

```bash
cd /opt/fishing-bot
sudo -u fishbot git pull
sudo -u fishbot .venv/bin/pip install -r requirements.txt   # если менялись зависимости
systemctl restart fishing-bot
```

## Полезные команды

```bash
systemctl restart fishing-bot   # перезапустить
systemctl stop fishing-bot      # остановить
journalctl -u fishing-bot -n 100 --no-pager   # последние 100 строк лога
```

---

## Карта (мини-приложение) — опционально

Кнопка «🗺 Карта» показывается только если задан публичный **HTTPS**-адрес в
`WEBAPP_URL` (Telegram WebApp работает только по https). Варианты:

1. **Быстро для теста:** туннель `cloudflared`
   (`cloudflared tunnel --url http://localhost:8080`) — даст временный
   https-адрес, впишите его в `WEBAPP_URL` и перезапустите сервис.
2. **По-взрослому:** домен + Nginx с сертификатом Let's Encrypt, проксирующий на
   `localhost:8080`. Тогда `WEBAPP_URL=https://ваш-домен`.

Без `WEBAPP_URL` бот полностью работает — дневник просто отдаётся списком в чате.
Для MVP этого достаточно; карту можно подключить позже.
