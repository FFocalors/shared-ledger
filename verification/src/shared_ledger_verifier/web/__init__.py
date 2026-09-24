"""Web package entry for Shared Ledger Verification Console."""

from __future__ import annotations

import sys
import threading
import time
import webbrowser

from .app import app


def start_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> int:
    """Start the Uvicorn server for the local dashboard."""
    import uvicorn

    url = f"http://{host}:{port}"
    print("=" * 60)
    print(f" Shared Ledger Verification Web Console")
    print(f" Web 控制台地址: {url}")
    print(f" 监听地址: {host}:{port} (仅限本地安全访问)")
    print(f" 按 Ctrl+C 停止服务")
    print("=" * 60)

    if open_browser:
        def _open() -> None:
            time.sleep(1.0)
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0
    except KeyboardInterrupt:
        print("\n服务已停止")
        return 0
    except Exception as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1


__all__ = ["app", "start_server"]
