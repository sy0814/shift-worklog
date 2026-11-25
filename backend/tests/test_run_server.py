"""run_server.py：Windows 服务直接用基础 Python 运行它（不经过 venv 的 python.exe 转接程序，停服务时不会留下进程）。
它要能用上 .venv 里装的包。"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def test_base_python_uses_venv_packages():
    base = getattr(sys, "_base_executable", sys.executable)
    code = (f"import sys; sys.path.insert(0, {str(HERE)!r}); import run_server; run_server.use_venv(); "
            "import fastapi, sqlalchemy, uvicorn; print('ok', fastapi.__file__)")
    r = subprocess.run([base, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("ok")
    if (HERE / ".venv").exists():  # 本地有 venv 时：包必须来自 venv
        assert ".venv" in r.stdout


def test_version_runs():
    base = getattr(sys, "_base_executable", sys.executable)
    r = subprocess.run([base, str(HERE / "run_server.py"), "--version"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "uvicorn" in r.stdout.lower(), r.stderr
