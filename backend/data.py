# -*- coding: utf-8 -*-
"""数据集生成与决策边界采样网格。

网格约定：行 0 对应 y 最大值（画布顶部），与前端 Canvas 的 y 轴方向一致，
前端拿到 uint8 网格后可以逐行直接绘制，不需要再翻转。
"""
import numpy as np
from sklearn.datasets import make_circles, make_moons

# 自定义手绘数据使用的坐标范围，与 make_moons 的原始尺度接近
CUSTOM_X = (-1.5, 2.5)
CUSTOM_Y = (-1.0, 1.5)


def build_dataset(kind: str, n_samples: int, noise: float,
                  data_seed: int, points: list) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(data_seed)
    if kind == "moons":
        X, y = make_moons(n_samples=n_samples, noise=noise, random_state=data_seed)
    elif kind == "circles":
        X, y = make_circles(n_samples=n_samples, noise=noise,
                            factor=0.5, random_state=data_seed)
    elif kind == "xor":
        X = rng.uniform(-1.0, 1.0, size=(n_samples, 2))
        y = (X[:, 0] * X[:, 1] > 0).astype(np.int64)
        X = X + rng.normal(0.0, noise, size=X.shape)
    elif kind == "custom":
        if len(points) < 4:
            raise ValueError("手绘数据集至少需要 4 个点，请先在数据画布上点几下")
        X = np.array([[p["x"], p["y"]] for p in points], dtype=np.float32)
        y = np.array([int(p["label"]) for p in points], dtype=np.int64)
        if len(np.unique(y)) < 2:
            raise ValueError("需要同时有红色（左键）和蓝色（右键）两类样本")
    else:
        raise ValueError(f"未知数据集: {kind}")
    return X.astype(np.float32), y.astype(np.int64)


def make_grid(X: np.ndarray, size: int, pad: float = 0.45):
    x_min, x_max = float(X[:, 0].min()) - pad, float(X[:, 0].max()) + pad
    y_min, y_max = float(X[:, 1].min()) - pad, float(X[:, 1].max()) + pad
    xs = np.linspace(x_min, x_max, size, dtype=np.float32)
    ys = np.linspace(y_max, y_min, size, dtype=np.float32)  # 行 0 = 顶部
    xx, yy = np.meshgrid(xs, ys)
    grid = np.stack([xx.ravel(), yy.ravel()], axis=1).astype(np.float32)
    meta = {
        "width": size, "height": size,
        "x_min": x_min, "x_max": x_max,
        "y_min": y_min, "y_max": y_max,
    }
    return grid, meta


def world_to_pixel(x: float, y: float, meta: dict, w: int, h: int):
    px = (x - meta["x_min"]) / (meta["x_max"] - meta["x_min"]) * w
    py = (meta["y_max"] - y) / (meta["y_max"] - meta["y_min"]) * h
    return px, py
