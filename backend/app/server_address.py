"""访问地址（服务器 IP / 电脑名）：网页「系统设置 → 访问地址」。

真正改地址的是 deploy/windows/set-address.ps1（改 HTTPS 服务 Caddy 的 SITE_HOSTS 并重启它），程序服务没有权限、
也不该自己去重启别的服务。所以和「立即备份」一样：网页把新地址写进 data\\site-hosts-request.txt，
再启动计划任务 WorkRecordSetAddress（以 SYSTEM 运行 set-address.ps1 -FromFile），结果写进 site-hosts-status.json。
地址格式的检查和 set-address.ps1 一致。
"""

import json
import os
import re
import socket
import subprocess

from .storage_service import data_dir

TASK = "WorkRecordSetAddress"  # deploy/windows/common.ps1 的 $TaskAddress
_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-.]*[A-Za-z0-9])?$")


def _read(name: str) -> str:
    try:
        return (data_dir() / name).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def normalize(text: str) -> str:
    """「192.168.1.60，worklog」→「192.168.1.60, worklog」；格式不对抛 ValueError（说明哪一个不对）。"""
    hosts = [h.strip() for h in re.split(r"[,，;；\s]+", text or "") if h.strip()]
    if not hosts:
        raise ValueError("address required")
    if len(hosts) > 5:
        raise ValueError("at most 5 addresses")
    for h in hosts:
        if m := _IPV4.match(h):
            if any(int(x) > 255 for x in m.groups()):
                raise ValueError(f"bad address: {h}")
        elif not _NAME.match(h) or len(h) > 63:
            raise ValueError(f"bad address: {h}")
    return ", ".join(dict.fromkeys(hosts))


def current() -> str:
    """现在的访问地址（安装 / 改地址时写的 data\\site-hosts.txt）。"""
    return _read("site-hosts.txt")


def status() -> dict | None:
    """上一次在网页上改地址的结果：{ok, at, hosts, message}；没改过为 None。"""
    try:
        return json.loads(_read("site-hosts-status.json") or "null")
    except ValueError:
        return None


def pending() -> str:
    """已经提交、计划任务还没处理的新地址（空 = 没有）。"""
    return _read("site-hosts-request.txt")


def candidates() -> list[str]:
    """这台服务器自己的 IPv4 地址和电脑名，给页面当「点一下就填上」的选项。"""
    ips: list[str] = []
    name = ""
    try:
        name = socket.gethostname()
        ips += [info[4][0] for info in socket.getaddrinfo(name, None, socket.AF_INET)]
    except OSError:
        pass
    try:  # 往外连时用的那张网卡（不真的发数据；内网没有外网路由时会失败，忽略）
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    out = list(dict.fromkeys(ip for ip in ips if not ip.startswith(("127.", "169.254.", "0."))))
    if name and _NAME.match(name):
        out.append(name)
    return out


def request(hosts: str) -> None:
    """提交新地址并启动计划任务（只在 Windows 服务器上能用）。"""
    if os.name != "nt":
        raise RuntimeError("only on the Windows server")
    (data_dir() / "site-hosts-request.txt").write_text(hosts, encoding="utf-8")
    r = subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True, timeout=30)  # noqa: S603,S607
    if r.returncode != 0:
        (data_dir() / "site-hosts-request.txt").unlink(missing_ok=True)
        raise RuntimeError("address task not found; run update.ps1 again")
