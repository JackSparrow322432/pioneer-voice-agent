"""
Проверка регистрации в Zadarma без Asterisk.
Запуск (из корня проекта, где .env):  python3 scripts/sip_test.py
Показывает ответ сервера по UDP и TCP для серверов Алматы и Германии.
"""
import hashlib
import random
import re
import socket
import string

HOSTS = ["sipal1.zadarma.com", "sip.zadarma.com"]
DOMAIN = "sip.zadarma.com"


def env(key):
    for line in open(".env", encoding="utf-8-sig"):
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


LOGIN, PASSWORD = env("ZADARMA_LOGIN"), env("ZADARMA_PASSWORD")
rnd = lambda n=10: "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
md5 = lambda s: hashlib.md5(s.encode()).hexdigest()


def local_ip(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((host, 5060))
    ip = s.getsockname()[0]
    s.close()
    return ip


def build(proto, lip, lport, cseq, call_id, tag, auth=""):
    return (f"REGISTER sip:{DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/{proto} {lip}:{lport};rport;branch=z9hG4bK{rnd()}\r\n"
            f"Max-Forwards: 70\r\n"
            f"From: <sip:{LOGIN}@{DOMAIN}>;tag={tag}\r\n"
            f"To: <sip:{LOGIN}@{DOMAIN}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq} REGISTER\r\n"
            f"Contact: <sip:{LOGIN}@{lip}:{lport};transport={proto.lower()}>\r\n"
            f"Expires: 60\r\n{auth}"
            f"User-Agent: pioneer-sip-test\r\nContent-Length: 0\r\n\r\n").encode()


def digest(resp_text):
    h = re.search(r'WWW-Authenticate:\s*Digest (.*)', resp_text, re.I)
    if not h:
        return ""
    p = dict(re.findall(r'(\w+)="?([^",]+)"?', h.group(1)))
    realm, nonce = p.get("realm", DOMAIN), p.get("nonce", "")
    uri = f"sip:{DOMAIN}"
    ha1, ha2 = md5(f"{LOGIN}:{realm}:{PASSWORD}"), md5(f"REGISTER:{uri}")
    if "auth" in p.get("qop", ""):
        cnonce, nc = rnd(8), "00000001"
        r = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")
        extra = f', qop=auth, nc={nc}, cnonce="{cnonce}"'
    else:
        r, extra = md5(f"{ha1}:{nonce}:{ha2}"), ""
    opaque = f', opaque="{p["opaque"]}"' if "opaque" in p else ""
    return (f'Authorization: Digest username="{LOGIN}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
            f'response="{r}", algorithm=MD5{extra}{opaque}\r\n')


def try_one(host, proto):
    ip = socket.gethostbyname(host)
    lip = local_ip(ip)
    call_id, tag = rnd(16), rnd(8)
    if proto == "UDP":
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", 0))
        send = lambda b: s.sendto(b, (ip, 5060))
        recv = lambda: s.recvfrom(65535)[0].decode(errors="ignore")
    else:
        s = socket.create_connection((ip, 5060), timeout=5)
        send = s.sendall
        recv = lambda: s.recv(65535).decode(errors="ignore")
    s.settimeout(5)
    lport = s.getsockname()[1]
    try:
        send(build(proto, lip, lport, 1, call_id, tag))
        r1 = recv()
        line1 = r1.split("\r\n")[0]
        if " 401 " not in line1 and " 407 " not in line1:
            return f"{line1}"
        send(build(proto, lip, lport, 2, call_id, tag, digest(r1)))
        r2 = recv()
        return f"{line1}  ->  {r2.split(chr(13))[0]}"
    except socket.timeout:
        return "НЕТ ОТВЕТА (таймаут)"
    except OSError as e:
        return f"ошибка сети: {e}"
    finally:
        s.close()


if __name__ == "__main__":
    if not LOGIN or not PASSWORD:
        raise SystemExit("В .env нет ZADARMA_LOGIN или ZADARMA_PASSWORD")
    print(f"Логин: {LOGIN}, длина пароля: {len(PASSWORD)} символов\n")
    for host in HOSTS:
        for proto in ("UDP", "TCP"):
            print(f"{host:22} {proto}:  {try_one(host, proto)}")
    print("\n200 OK = логин и пароль верны, сеть работает."
          "\n403 Forbidden = неверный пароль."
          "\nНЕТ ОТВЕТА = запрос не доходит (роутер/SIP ALG).")
