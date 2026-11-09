# -*- coding: utf-8 -*-
"""Backprop Lab · FastAPI 应用入口

REST：实验 CRUD / 网络目录 / 数据集预览
WS  ：/ws/experiments/{id} 流式推送 meta / metric / frame / done
静态：/ 返回前端单页，/static 提供 css 与 js
"""
import asyncio
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .data import CUSTOM_X, CUSTOM_Y, build_dataset, make_grid
from .hub import Hub
from .networks import network_catalog
from .schema import ExperimentConfig
from .storage import Store
from .trainer import NETWORK_CATALOG, run_training

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="Backprop Lab · 神经网络训练显微镜",
    description="把一次 BP 训练的内部状态变成可拖动、可回放、可对比的时间轴",
    version="0.1.0",
)
hub = Hub()
store = Store()


@app.get("/api/health")
def health():
    """部署平台健康检查探针：不查库、不触发训练，秒级返回。"""
    return {"status": "ok", "version": app.version}


@app.get("/api/networks")
def get_networks():
    """网络目录：结构、参数量、激活函数、预期结论。"""
    return {"networks": network_catalog()}


@app.get("/api/datasets/{kind}")
def preview_dataset(kind: str, n_samples: int = 200, noise: float = 0.1,
                    data_seed: int = 42):
    """切换数据集时先给前端一份预览点，不必等训练开始。"""
    if kind == "custom":
        meta = {"width": 48, "height": 48,
                "x_min": CUSTOM_X[0], "x_max": CUSTOM_X[1],
                "y_min": CUSTOM_Y[0], "y_max": CUSTOM_Y[1]}
        return {"points": {"x": [], "y": [], "label": []}, "grid": meta}
    try:
        X, y = build_dataset(kind, n_samples, noise, data_seed, [])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _, meta = make_grid(X, 48)
    return {"points": {"x": X[:, 0].round(4).tolist(),
                       "y": X[:, 1].round(4).tolist(),
                       "label": y.tolist()}, "grid": meta}


@app.post("/api/experiments", status_code=201)
async def create_experiment(cfg: ExperimentConfig):
    """创建实验并在后台线程启动训练，返回 exp_id 供 WebSocket 订阅。"""
    if cfg.dataset == "custom" and len(cfg.points) < 4:
        raise HTTPException(status_code=400, detail="手绘数据集至少需要 4 个点")
    exp_id = uuid.uuid4().hex[:12]
    name = cfg.name or f"{cfg.network} 号 · {cfg.dataset}"
    hub.create(exp_id)
    store.create_experiment(exp_id, cfg, name)
    loop = asyncio.get_running_loop()
    threading.Thread(
        target=run_training,
        args=(exp_id, cfg, hub, loop, store, NETWORK_CATALOG),
        daemon=True,
    ).start()
    return {"id": exp_id, "name": name, "network": cfg.network,
            "dataset": cfg.dataset, "epochs": cfg.epochs, "lr": cfg.lr,
            "status": "running"}


@app.get("/api/experiments")
def list_experiments(limit: int = 50):
    return {"experiments": store.list_experiments(limit)}


@app.get("/api/experiments/{exp_id}")
def get_experiment(exp_id: str):
    data = store.get_experiment(exp_id)
    if data is None:
        raise HTTPException(status_code=404, detail="实验不存在")
    return data


@app.websocket("/ws/experiments/{exp_id}")
async def experiment_stream(websocket: WebSocket, exp_id: str):
    await websocket.accept()
    queue, history = hub.subscribe(exp_id)
    try:
        if hub.get(exp_id) is None and not history:
            await websocket.send_json({
                "type": "error",
                "message": "该实验来自服务重启之前，请用 REST 接口 /api/experiments/{id} 回放快照",
            })
            return
        for event in history:
            await websocket.send_json(event)
        if any(e.get("type") in ("done", "error") for e in history):
            return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "error", "message": "等待训练事件超时"})
                break
            await websocket.send_json(event)
            if event.get("type") in ("done", "error"):
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(exp_id, queue)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
