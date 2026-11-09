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
    # 本地默认只监听回环地址；Docker / 云主机部署时设 HOST=0.0.0.0
    host = os.environ.get("HOST", "127.0.0.1")
    url = f"http://127.0.0.1:{port}"
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
