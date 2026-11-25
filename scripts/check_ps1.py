"""检查 Windows 部署脚本的格式：.ps1 必须 UTF-8 带 BOM + CRLF（Windows PowerShell 5.1 否则中文乱码），
alembic.ini 必须纯 ASCII（中文 Windows 按 GBK 读）。CI 里跑，本地也可以直接 python scripts/check_ps1.py。"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
bad = []
for p in sorted((root / "deploy" / "windows").glob("*.ps1")):
    b = p.read_bytes()
    if not b.startswith(b"\xef\xbb\xbf"):
        bad.append(f"{p.relative_to(root)}: 没有 UTF-8 BOM")
    try:
        b.decode("utf-8-sig")
    except UnicodeDecodeError:
        bad.append(f"{p.relative_to(root)}: 不是 UTF-8")
    if b.replace(b"\r\n", b"").count(b"\n"):
        bad.append(f"{p.relative_to(root)}: 有 LF 换行（要 CRLF）")
ini = root / "backend" / "alembic.ini"
if not ini.read_bytes().isascii():
    bad.append("backend/alembic.ini: 有非 ASCII 字符")
print("\n".join(bad) or "OK")
sys.exit(1 if bad else 0)
