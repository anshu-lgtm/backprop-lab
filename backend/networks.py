# -*- coding: utf-8 -*-
"""
网络注册表：A ~ F 号 nn.Sequential 结构。

与第 11 周作业 ai_test_11_9/networks.py 完全一致，保留创建顺序，
目的是复现课件里那组「按 A->F 顺序连续创建、随机状态自然推进」的初始化。
不要给每个网络单独重置种子：D 号（2 层 ReLU）在某些初始化下会
出现「神经元全部死亡」，loss 卡在 0.6931、准确率 50%。
"""
from typing import Callable

import torch
import torch.nn as nn


def build_model_a():
    return nn.Sequential(nn.Linear(2, 10), nn.Linear(10, 2))


def build_model_b():
    return nn.Sequential(
        nn.Linear(2, 20), nn.Linear(20, 5), nn.Linear(5, 30),
        nn.Linear(30, 5), nn.Linear(5, 2),
    )


def build_model_c():
    return nn.Sequential(
        nn.Linear(2, 20), nn.Linear(20, 5), nn.Linear(5, 30),
        nn.ReLU(), nn.Linear(30, 5), nn.Linear(5, 2),
    )


def build_model_d():
    return nn.Sequential(nn.Linear(2, 5), nn.ReLU(), nn.Linear(5, 2))


def build_model_e():
    return nn.Sequential(nn.Linear(2, 5), nn.Sigmoid(), nn.Linear(5, 2))


def build_model_f():
    return nn.Sequential(
        nn.Linear(2, 16), nn.ReLU(),
        nn.Linear(16, 16), nn.ReLU(),
        nn.Linear(16, 2),
    )


# (标签, 名称, 结构串, 激活函数, 结论, 构造函数)
NETWORKS = [
    ("A", "二层线性", "2-10-2", "无", "分界线是直线，划不开月亮数据", build_model_a),
    ("B", "五层线性", "2-20-5-30-5-2", "无", "堆到 5 层仍是线性变换，边界依旧是直线", build_model_b),
    ("C", "五层 + ReLU", "2-20-5-30-5-2", "ReLU", "多个 ReLU 拼出弯折边界，完美划分", build_model_c),
    ("D", "二层 + ReLU", "2-5-2", "ReLU", "只有 5 个神经元，折线段不够，欠拟合", build_model_d),
    ("E", "二层 + Sigmoid", "2-5-2", "Sigmoid", "平滑弯曲边界，正确但收敛更慢", build_model_e),
    ("F", "自建双隐藏层", "2-16-16-2", "ReLU", "分段数量充足，边界平滑且快速收敛", build_model_f),
]

BuildersType = dict[str, Callable[[], nn.Sequential]]


def build_all(seed: int) -> BuildersType:
    """按 A->F 顺序创建全部网络，返回 tag -> model 字典。"""
    torch.manual_seed(seed)
    return {tag: fn() for tag, _, _, _, _, fn in NETWORKS}


def network_catalog() -> list[dict]:
    out = []
    for tag, name, shape, act, note, fn in NETWORKS:
        m = fn()
        params = sum(p.numel() for p in m.parameters())
        layers = [("Linear" if isinstance(x, nn.Linear) else type(x).__name__)
                  for x in m]
        out.append({
            "tag": tag, "name": name, "shape": shape, "activation": act,
            "note": note, "params": params, "layers": layers,
        })
    return out
