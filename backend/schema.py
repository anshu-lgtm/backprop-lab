# -*- coding: utf-8 -*-
"""请求 / 响应数据模型（Pydantic v2）"""
from typing import Literal

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float
    label: int = Field(ge=0, le=1)


class ExperimentConfig(BaseModel):
    network: Literal["A", "B", "C", "D", "E", "F"] = "D"
    dataset: Literal["moons", "circles", "xor", "custom"] = "moons"
    n_samples: int = Field(default=200, ge=20, le=1000)
    noise: float = Field(default=0.1, ge=0.0, le=0.5)
    epochs: int = Field(default=1000, ge=10, le=5000)
    lr: float = Field(default=0.1, gt=0.0, le=1.0)
    seed: int = Field(default=13, ge=0, le=100000)
    data_seed: int = Field(default=42, ge=0, le=100000)
    frame_every: int = Field(default=20, ge=1, le=200)
    grid_size: int = Field(default=48, ge=16, le=96)
    points: list[Point] = Field(default_factory=list)
    name: str = Field(default="", max_length=80)


class ExperimentOut(BaseModel):
    id: str
    name: str
    network: str
    dataset: str
    epochs: int
    lr: float
    status: str
