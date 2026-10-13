"""Railway 等云平台入口: 复用 agent.server 的 FastAPI app。

本地开发仍可用 `python agent/server.py`(绑定 127.0.0.1:8000);
云端(如 Railway): `uvicorn main:app --host 0.0.0.0 --port $PORT`。
"""
import os

from agent.server import app  # noqa: F401  (供 `uvicorn main:app` 引用)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
