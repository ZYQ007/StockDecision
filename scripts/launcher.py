"""本机启动器：设置数据目录与通达信路径，启动服务并打开浏览器。

关闭本终端窗口或按 Ctrl+C 即停止服务。
Windows / macOS 均可：python scripts/launcher.py
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "买入时机"
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"


def install_root() -> Path:
    """安装根目录：含 app/ 与 runtime/（安装包）或项目根（开发）。"""
    here = Path(__file__).resolve().parent
    root = here.parent
    if (root / "app" / "main.py").is_file():
        return root
    if (here / "app" / "main.py").is_file():
        return here
    # macOS .app: Contents/Resources/…
    resources = here.parent / "Resources"
    if (resources / "app" / "main.py").is_file():
        return resources
    return root


def app_data_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / "launcher.json"


def load_user_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_user_config(data: dict) -> None:
    config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_tdx_home(saved: str | None = None) -> Path | None:
    """通达信主要为 Windows 客户端；macOS 一般检测不到，属预期。"""
    candidates: list[Path] = []
    if saved:
        candidates.append(Path(saved))
    env = os.environ.get("STOCKDECISION_TDX_HOME") or os.environ.get("TDX_HOME")
    if env:
        candidates.append(Path(env))
    if sys.platform == "win32":
        candidates.extend(
            [
                Path(r"D:\new_tdx"),
                Path(r"C:\new_tdx"),
                Path(r"D:\tdx"),
                Path(r"C:\tdx"),
                Path(r"C:\Program Files\new_tdx"),
                Path(r"C:\Program Files (x86)\new_tdx"),
            ]
        )
    else:
        # 少数用户在 Mac 上挂载了 Windows 盘或手动拷贝了 connect.cfg
        home = Path.home()
        candidates.extend(
            [
                home / "new_tdx",
                home / "tdx",
                Path("/Volumes/new_tdx"),
                Path("/opt/new_tdx"),
            ]
        )
    for path in candidates:
        if path and (path / "connect.cfg").is_file():
            return path
    return None


def resolve_python(root: Path) -> Path:
    # Windows 便携 runtime
    win_py = root / "runtime" / "python.exe"
    if win_py.is_file():
        return win_py
    # python-build-standalone / 官方框架便携布局
    for rel in (
        Path("runtime") / "bin" / "python3",
        Path("runtime") / "bin" / "python",
        Path("runtime") / "python" / "bin" / "python3",
    ):
        mac_py = root / rel
        if mac_py.is_file() and os.access(mac_py, os.X_OK):
            return mac_py
    return Path(sys.executable)


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def wait_ready(timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    health = f"http://{HOST}:{PORT}/api/health"
    while time.time() < deadline:
        if port_open(HOST, PORT):
            try:
                with urllib.request.urlopen(health, timeout=1.5) as resp:
                    if resp.status == 200:
                        return True
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
        time.sleep(0.4)
    return False


def prepare_env(root: Path) -> dict:
    env = os.environ.copy()
    data = app_data_dir()
    db = data / "market.db"
    user = load_user_config()
    tdx = detect_tdx_home(user.get("tdx_home"))
    if tdx:
        user["tdx_home"] = str(tdx)
        save_user_config(user)
        env["STOCKDECISION_TDX_HOME"] = str(tdx)
        env["TDX_HOME"] = str(tdx)
    env["STOCKDECISION_DB_PATH"] = str(db)
    env["DB_PATH"] = str(db)
    env["STOCKDECISION_HOST"] = HOST
    env["STOCKDECISION_PORT"] = str(PORT)
    env["HOST"] = HOST
    env["PORT"] = str(PORT)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(root) + (os.pathsep + prev if prev else "")
    return env


def main() -> int:
    root = install_root()
    python = resolve_python(root)
    env = prepare_env(root)
    data = app_data_dir()
    tdx = env.get("STOCKDECISION_TDX_HOME")

    print(f"{APP_NAME} 启动器")
    print(f"  系统:     {sys.platform}")
    print(f"  安装目录: {root}")
    print(f"  数据目录: {data}")
    print(f"  Python:   {python}")
    if tdx:
        print(f"  通达信:   {tdx}")
    else:
        if sys.platform == "darwin":
            print("  通达信:   macOS 通常无通达信客户端，将使用备用行情主站（能力可能降级）")
        else:
            print("  通达信:   未检测到（将使用备用主站，部分能力可能降级）")
            print("            可设置环境变量 TDX_HOME 指向含 connect.cfg 的目录后重启。")
    print(f"  地址:     {URL}")
    print("  关闭本窗口或按 Ctrl+C 停止服务。")
    print()

    if port_open(HOST, PORT):
        print(f"端口 {PORT} 已被占用，尝试直接打开浏览器…")
        webbrowser.open(URL)
        print("若页面不对，请先结束占用该端口的进程后再启动。")
        try:
            input("按回车键退出启动器…")
        except EOFError:
            pass
        return 0

    proc = subprocess.Popen(
        [str(python), "-m", "app"],
        cwd=str(root),
        env=env,
    )

    def _shutdown(*_args) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    signal.signal(signal.SIGINT, lambda *_: _shutdown())
    signal.signal(signal.SIGTERM, lambda *_: _shutdown())

    try:
        if wait_ready():
            webbrowser.open(URL)
            print("服务已就绪，浏览器应已打开。")
        else:
            print("等待服务就绪超时，请检查上方错误输出，或稍后手动打开：", URL)
            webbrowser.open(URL)
        proc.wait()
    except KeyboardInterrupt:
        _shutdown()
    finally:
        if proc.poll() is None:
            _shutdown()
    return proc.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
