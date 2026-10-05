#!/usr/bin/env bash
# Установка агента на VPS Ubuntu 22.04/24.04 (запуск от root из папки проекта):
#   sudo bash setup_vps.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
[ -f .env ] || { echo "Нет файла .env — скопируйте .env.example в .env и заполните"; exit 1; }
sed -i '1s/^\xEF\xBB\xBF//; s/\r$//' .env   # .env из Блокнота Windows: убрать BOM и CRLF
echo "==> Настройки из .env прочитаны"

get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d '\r' || true; }
setenv() {  # записать KEY=VALUE в .env
  if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}

ZLOGIN="$(get ZADARMA_LOGIN)"; ZPASS="$(get ZADARMA_PASSWORD)"
[ -n "$ZLOGIN" ] && [ -n "$ZPASS" ] || { echo "Заполните ZADARMA_LOGIN и ZADARMA_PASSWORD в .env"; exit 1; }
[ -n "$(get OPENAI_API_KEY)" ] || { echo "Заполните OPENAI_API_KEY в .env"; exit 1; }

AMI_SECRET="$(get AMI_SECRET)"
if [ -z "$AMI_SECRET" ]; then AMI_SECRET="$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"; setenv AMI_SECRET "$AMI_SECRET"; fi
HTTP_PORT="$(get HTTP_PORT)"; HTTP_PORT="${HTTP_PORT:-5050}"
ZSERVER="$(get ZADARMA_SERVER)"; ZSERVER="${ZSERVER:-sipal1.zadarma.com}"
ZPROTO="$(get ZADARMA_PROTO)"; ZPROTO="${ZPROTO:-tcp}"

echo "==> Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q asterisk python3-venv python3-pip ufw curl

echo "==> Конфиги Asterisk"
for f in pjsip extensions manager rtp; do
  [ -f "/etc/asterisk/$f.conf.orig" ] || cp -f "/etc/asterisk/$f.conf" "/etc/asterisk/$f.conf.orig" 2>/dev/null || true
  ZLOGIN="$ZLOGIN" ZPASS="$ZPASS" AMI_SECRET="$AMI_SECRET" HTTP_PORT="$HTTP_PORT" ZSERVER="$ZSERVER" ZPROTO="$ZPROTO" python3 - "asterisk/$f.conf" "/etc/asterisk/$f.conf" <<'PY'
import os, sys
s = open(sys.argv[1], encoding="utf-8").read()
for k, v in {"{{ZADARMA_LOGIN}}": os.environ["ZLOGIN"], "{{ZADARMA_PASSWORD}}": os.environ["ZPASS"],
             "{{AMI_SECRET}}": os.environ["AMI_SECRET"],
             "{{ZADARMA_SERVER}}": os.environ["ZSERVER"], "{{ZADARMA_PROTO}}": os.environ["ZPROTO"],
             "{{ZADARMA_TRANSPORT}}": "transport-" + os.environ["ZPROTO"], "127.0.0.1:5050": "127.0.0.1:" + os.environ["HTTP_PORT"]}.items():
    s = s.replace(k, v)
open(sys.argv[2], "w", encoding="utf-8").write(s)
PY
done
chown asterisk:asterisk /etc/asterisk/*.conf 2>/dev/null || true
chmod 640 /etc/asterisk/pjsip.conf /etc/asterisk/manager.conf
systemctl enable asterisk
systemctl restart asterisk
sleep 3

echo "==> Python"
[ -d .venv/Scripts ] && rm -rf .venv   # окружение, скопированное с Windows, не подходит
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Сервис pioneer-agent"
cat > /etc/systemd/system/pioneer-agent.service <<EOF
[Unit]
Description=Pioneer AI voice sales agent
After=network-online.target asterisk.service

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable pioneer-agent
systemctl restart pioneer-agent

echo "==> Файрвол"
if grep -qi microsoft /proc/version; then
  echo "WSL: файрвол Linux не трогаем"
else
  ufw allow OpenSSH >/dev/null || true
  ufw allow 5060/udp >/dev/null || true
  ufw allow 10000:20000/udp >/dev/null || true
  ufw allow "$HTTP_PORT"/tcp >/dev/null || true
  ufw --force enable >/dev/null || true
fi

sleep 2
echo
echo "==> Проверка"
asterisk -rx "pjsip show registrations" || true
systemctl --no-pager --lines=0 status pioneer-agent | head -3 || true
IP="$(curl -s -4 ifconfig.me || hostname -I | awk '{print $1}')"
echo
echo "Готово. Панель: http://$IP:$HTTP_PORT"
echo "Регистрация в Zadarma должна быть в статусе Registered (см. выше)."
echo "Логи агента:    journalctl -u pioneer-agent -f"
echo "Консоль Asterisk: asterisk -rvvv"
