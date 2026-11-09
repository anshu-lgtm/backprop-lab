# -*- coding: utf-8 -*-
"""PyTorch 训练引擎：逐轮采集指标，按间隔采集决策边界关键帧。

训练循环严格保持课件里的四步：前向传播 -> 计算误差 -> 反向传播 -> 更新参数。
额外用 forward hook 抓取激活层输出，用来做「死 ReLU」检测和激活热力图。
"""
import base64
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from .data import build_dataset, make_grid
from .networks import build_all, network_catalog
from .schema import ExperimentConfig


def _activation_probe(model: nn.Sequential):
    """给激活层挂 hook，返回 (handles, slots)。"""
    slots: dict[int, torch.Tensor] = {}
    handles = []
    for idx, layer in enumerate(model):
        if isinstance(layer, (nn.ReLU, nn.Sigmoid)):
            def hook(_mod, _inp, out, i=idx):
                slots[i] = out.detach()
            handles.append(layer.register_forward_hook(hook))
    return handles, slots


def _read_activations(model: nn.Sequential, slots: dict):
    layers, dead_parts = [], []
    for idx, layer in enumerate(model):
        tensor = slots.get(idx)
        if tensor is None:
            continue
        kind = type(layer).__name__
        means = tensor.mean(dim=0).cpu().numpy().round(4).tolist()
        layers.append({"layer": idx, "kind": kind,
                       "values": [round(float(v), 4) for v in means]})
        if kind == "ReLU":
            dead_parts.append(float((tensor == 0).float().mean().item()))
    dead = float(np.mean(dead_parts)) if dead_parts else 0.0
    return layers, dead


def run_training(exp_id: str, cfg: ExperimentConfig, hub, loop, store, catalog: dict):
    emit = lambda ev: hub.publish_from_thread(loop, exp_id, ev)
    started = time.perf_counter()
    try:
        points = [p.model_dump() for p in cfg.points]
        X_np, y_np = build_dataset(cfg.dataset, cfg.n_samples, cfg.noise,
                                   cfg.data_seed, points)
        X = torch.from_numpy(X_np)
        y = torch.from_numpy(y_np)

        grid_np, grid_meta = make_grid(X_np, cfg.grid_size)
        grid_t = torch.from_numpy(grid_np)
        store.set_grid_meta(exp_id, grid_meta)

        models = build_all(cfg.seed)
        model = models[cfg.network]
        model.train()
        handles, slots = _activation_probe(model)

        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=cfg.lr)

        step = cfg.frame_every
        while cfg.epochs // step + 2 > 200:       # 最多 200 帧，防止长训练压垮浏览器
            step *= 2

        info = catalog[cfg.network]
        emit({
            "type": "meta",
            "exp_id": exp_id,
            "network": cfg.network,
            "network_info": info,
            "dataset": cfg.dataset,
            "epochs": cfg.epochs,
            "lr": cfg.lr,
            "seed": cfg.seed,
            "frame_every": step,
            "grid": grid_meta,
            "points": {"x": X_np[:, 0].round(4).tolist(),
                       "y": X_np[:, 1].round(4).tolist(),
                       "label": y_np.tolist()},
            "activation_layers": [
                {"layer": i, "kind": type(m).__name__}
                for i, m in enumerate(model) if isinstance(m, (nn.ReLU, nn.Sigmoid))
            ],
        })

        size = cfg.grid_size
        metric_buf: list[tuple] = []
        act_buf: list[tuple] = []
        frame_epochs = {0, cfg.epochs - 1}
        frame_epochs.update(range(0, cfg.epochs, step))
        last_loss = last_acc = 0.0

        for epoch in range(cfg.epochs):
            y_pred = model(X)                       # 1. 前向传播
            loss = criterion(y_pred, y)             # 2. 计算误差
            optimizer.zero_grad()                   # 3. 反向传播（BP）
            loss.backward()
            grad_sq = sum(float(p.grad.pow(2).sum().item())
                          for p in model.parameters() if p.grad is not None)
            grad_norm = math.sqrt(grad_sq)
            optimizer.step()                        # 4. 更新参数

            last_loss = float(loss.item())
            last_acc = float((y_pred.argmax(dim=1) == y).float().mean().item())
            activations, dead = _read_activations(model, slots)

            metric_buf.append((exp_id, epoch, last_loss, last_acc, grad_norm, dead))
            act_buf.append((exp_id, epoch,
                            json.dumps(activations, separators=(",", ":"))))
            emit({"type": "metric", "epoch": epoch, "loss": round(last_loss, 6),
                  "acc": round(last_acc, 4), "grad_norm": round(grad_norm, 6),
                  "dead_ratio": round(dead, 4), "activations": activations})

            if epoch in frame_epochs:
                with torch.no_grad():
                    prob = torch.softmax(model(grid_t), dim=1)[:, 1].cpu().numpy()
                blob = np.clip(np.round(prob * 255), 0, 255).astype(np.uint8).tobytes()
                store.add_frame(exp_id, epoch, size, size, blob)
                emit({"type": "frame", "epoch": epoch, "width": size,
                      "height": size, "data": base64.b64encode(blob).decode("ascii")})

            if len(metric_buf) >= 100:
                store.add_metrics(metric_buf)
                store.add_activations(act_buf)
                metric_buf.clear()
                act_buf.clear()

        store.add_metrics(metric_buf)
        store.add_activations(act_buf)
        for h in handles:
            h.remove()

        elapsed = round(time.perf_counter() - started, 3)
        store.finish(exp_id, "done", last_loss, last_acc, elapsed)
        emit({"type": "done", "final_loss": round(last_loss, 6),
              "final_acc": round(last_acc, 4), "elapsed": elapsed})
    except Exception as exc:                         # noqa: BLE001 - 推给前端展示
        store.finish(exp_id, "error")
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})


NETWORK_CATALOG = {row["tag"]: row for row in network_catalog()}
