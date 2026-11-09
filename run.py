# -*- coding: utf-8 -*-
"""一键启动：python run.py  （--no-browser 可禁用自动打开浏览器）"""
import os
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    port = int(os.environ.get("PORT", "8000"))
    # 平台（Docker / PaaS / 部署沙箱）会注入 PORT，此时必须对外绑定 0.0.0.0；
    # 本机直接运行时默认只监听回环地址，更安全。也可用 HOST 显式覆盖。
    host = os.environ.get("HOST") or (
        "0.0.0.0" if "PORT" in os.environ else "127.0.0.1")
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"
    print("=" * 62)
    print("  Backprop Lab · 神经网络训练显微镜")
    print(f"  页面     {url}")
    print(f"  API 文档 {url}/docs")
    print("  按 Ctrl+C 停止")
    print("=" * 62)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("backend.app:app", host=host, port=port,
                reload=False, log_level="info")


if __name__ == "__main__":
    main()
