"""
launch.py — RAG Scholar 打包入口
双击 exe 后自动启动 Flask 并打开浏览器
"""

import sys
import os
import threading
import webbrowser
import time
from pathlib import Path

# ── 确定运行目录（打包后资源路径会变） ────────────────────────────────────────
if getattr(sys, "frozen", False):
    # PyInstaller 打包后，资源在 _MEIPASS 临时目录
    BASE_DIR = Path(sys.executable).parent
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent
    BUNDLE_DIR = BASE_DIR

# ── 把 bundle 目录加入路径，让 Flask 能找到 templates ─────────────────────────
os.chdir(str(BASE_DIR))
sys.path.insert(0, str(BUNDLE_DIR))

# ── 设置数据目录（papers / chroma_db 放在 exe 同级） ─────────────────────────
PAPERS_DIR = BASE_DIR / "papers"
CHROMA_DIR = BASE_DIR / "chroma_db"
PAPERS_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

# ── 加载 .env ────────────────────────────────────────────────────────────────
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ── 覆盖 app.py 里的路径配置 ─────────────────────────────────────────────────
os.environ["RAG_PAPERS_DIR"] = str(PAPERS_DIR)
os.environ["RAG_CHROMA_DIR"] = str(CHROMA_DIR)
os.environ["RAG_BUNDLE_DIR"] = str(BUNDLE_DIR)

# ── 延迟打开浏览器 ────────────────────────────────────────────────────────────
def open_browser():
    time.sleep(2.5)
    webbrowser.open("http://localhost:5000")

threading.Thread(target=open_browser, daemon=True).start()

# ── 启动 Flask ────────────────────────────────────────────────────────────────
from app import app

print("=" * 50)
print("  文献语义检索系统 已启动")
print("  浏览器将自动打开，如未打开请访问：")
print("  http://localhost:5000")
print("  关闭此窗口将停止系统")
print("=" * 50)

app.run(host="127.0.0.1", port=5000, debug=False)