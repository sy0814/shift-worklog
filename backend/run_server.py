"""Windows 服务的启动入口：用基础 Python 直接运行，不经过 .venv\\Scripts\\python.exe。

原因：Windows 上 venv 里的 python.exe 只是个转接程序，它会再启动真正的 Python 来运行系统。停服务时
WinSW 结束了转接程序，真正的进程却可能留下来，一直占着 8000 端口，之后服务再也启动不了（报 10048）。
直接用基础 Python 运行这个文件就只有一个进程，停服务时一起结束。

这里做的事和 venv 一样：用 .venv 里装的包（优先于、并且不用基础 Python 自己装的包），然后启动 uvicorn。
用法（参数原样交给 uvicorn）：python run_server.py app.main:app --host 127.0.0.1 --port 8000 ...
"""

import glob
import os
import site
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")


def _venv_site_packages() -> str | None:
    for p in [os.path.join(VENV, "Lib", "site-packages"), *glob.glob(os.path.join(VENV, "lib", "python*", "site-packages"))]:
        if os.path.isdir(p):
            return p
    return None


def use_venv() -> None:
    sp = _venv_site_packages()
    if sp is None or os.path.normcase(os.path.abspath(sys.prefix)) == os.path.normcase(VENV):
        return  # 没有 venv，或者本来就是用 venv 的 Python 启动的
    # 和 venv 一样不用基础 Python 自己的 site-packages（免得版本冲突）
    sys.path[:] = [p for p in sys.path if not p.rstrip("\\/").lower().endswith("site-packages")]
    before = list(sys.path)
    site.addsitedir(sp)  # 会处理 .pth 文件（有的包靠它）
    added = [p for p in sys.path if p not in before]
    sys.path[:] = added + before
    os.environ["VIRTUAL_ENV"] = VENV


def main() -> None:
    use_venv()
    if HERE not in sys.path:
        sys.path.insert(0, HERE)  # app 包
    import uvicorn

    sys.argv = ["uvicorn", *sys.argv[1:]]
    sys.exit(uvicorn.main())


if __name__ == "__main__":
    main()
