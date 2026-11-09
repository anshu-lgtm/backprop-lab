# -*- coding: utf-8 -*-
"""SQLite 快照存储：实验元数据、逐轮指标、决策边界关键帧。"""
import base64
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "lab.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    network         TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    epochs          INTEGER NOT NULL,
    lr              REAL NOT NULL,
    seed            INTEGER NOT NULL,
    grid_size       INTEGER NOT NULL,
    config_json     TEXT NOT NULL,
    grid_meta_json  TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    final_loss      REAL,
    final_acc       REAL,
    elapsed         REAL,
    created_at      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
    exp_id     TEXT NOT NULL,
    epoch      INTEGER NOT NULL,
    loss       REAL NOT NULL,
    acc        REAL NOT NULL,
    grad_norm  REAL NOT NULL,
    dead_ratio REAL NOT NULL,
    PRIMARY KEY (exp_id, epoch)
);
CREATE TABLE IF NOT EXISTS frames (
    exp_id  TEXT NOT NULL,
    epoch   INTEGER NOT NULL,
    width   INTEGER NOT NULL,
    height  INTEGER NOT NULL,
    probs   BLOB NOT NULL,
    PRIMARY KEY (exp_id, epoch)
);
CREATE TABLE IF NOT EXISTS activations (
    exp_id     TEXT NOT NULL,
    epoch      INTEGER NOT NULL,
    data_json  TEXT NOT NULL,
    PRIMARY KEY (exp_id, epoch)
);
CREATE INDEX IF NOT EXISTS idx_metrics_exp ON metrics(exp_id);
CREATE INDEX IF NOT EXISTS idx_exp_created ON experiments(created_at DESC);
"""


class Store:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def session(self):
        """每次操作独立连接：训练线程与请求线程并发写也不会互相踩到。

        sqlite3 的 `with conn` 只负责事务，不会关闭连接，必须显式 close，
        否则 Windows 上临时库会被句柄锁住无法删除。
        """
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_experiment(self, exp_id: str, cfg, name: str):
        with self.session() as conn:
            conn.execute(
                "INSERT INTO experiments (id,name,network,dataset,epochs,lr,seed,"
                "grid_size,config_json,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (exp_id, name, cfg.network, cfg.dataset, cfg.epochs, cfg.lr,
                 cfg.seed, cfg.grid_size, cfg.model_dump_json(), "running", time.time()),
            )

    def set_grid_meta(self, exp_id: str, meta: dict):
        with self.session() as conn:
            conn.execute("UPDATE experiments SET grid_meta_json=? WHERE id=?",
                         (json.dumps(meta), exp_id))

    def add_metrics(self, rows: list[tuple]):
        if not rows:
            return
        with self.session() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO metrics "
                "(exp_id,epoch,loss,acc,grad_norm,dead_ratio) VALUES (?,?,?,?,?,?)", rows)

    def add_frame(self, exp_id: str, epoch: int, w: int, h: int, blob: bytes):
        with self.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO frames (exp_id,epoch,width,height,probs) "
                "VALUES (?,?,?,?,?)", (exp_id, epoch, w, h, blob))

    def add_activations(self, rows: list[tuple]):
        if not rows:
            return
        with self.session() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO activations (exp_id,epoch,data_json) "
                "VALUES (?,?,?)", rows)

    def finish(self, exp_id: str, status: str, loss=None, acc=None, elapsed=None):
        with self.session() as conn:
            conn.execute(
                "UPDATE experiments SET status=?, final_loss=?, final_acc=?, elapsed=? "
                "WHERE id=?", (status, loss, acc, elapsed, exp_id))

    def list_experiments(self, limit: int = 50):
        with self.session() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id,name,network,dataset,epochs,lr,seed,status,final_loss,"
                "final_acc,elapsed,created_at FROM experiments "
                "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_experiment(self, exp_id: str):
        with self.session() as conn:
            conn.row_factory = sqlite3.Row
            exp = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
            if exp is None:
                return None
            result = dict(exp)
            m = conn.execute(
                "SELECT epoch,loss,acc,grad_norm,dead_ratio FROM metrics "
                "WHERE exp_id=? ORDER BY epoch", (exp_id,)).fetchall()
            result["metrics"] = [dict(r) for r in m]
            a = conn.execute(
                "SELECT epoch,data_json FROM activations WHERE exp_id=?",
                (exp_id,)).fetchall()
            act_map = {r["epoch"]: json.loads(r["data_json"]) for r in a}
            for row in result["metrics"]:
                row["activations"] = act_map.get(row["epoch"], [])
            f = conn.execute(
                "SELECT epoch,width,height,probs FROM frames WHERE exp_id=? ORDER BY epoch",
                (exp_id,)).fetchall()
            result["frames"] = [
                {"epoch": r["epoch"], "width": r["width"], "height": r["height"],
                 "probs": base64.b64encode(r["probs"]).decode("ascii")}
                for r in f
            ]
        result["grid_meta"] = json.loads(result.pop("grid_meta_json") or "null")
        result["config"] = json.loads(result.pop("config_json") or "{}")
        return result
