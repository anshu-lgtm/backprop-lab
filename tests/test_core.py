# -*- coding: utf-8 -*-
"""核心逻辑单元测试：python -m unittest discover -s tests -v"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from backend.data import build_dataset, make_grid, world_to_pixel  # noqa: E402
from backend.networks import build_all, network_catalog  # noqa: E402
from backend.schema import ExperimentConfig  # noqa: E402
from backend.storage import Store  # noqa: E402
from backend.trainer import NETWORK_CATALOG, run_training  # noqa: E402


class FakeHub:
    def __init__(self):
        self.events = []

    def publish_from_thread(self, loop, exp_id, event):
        self.events.append(event)


class TestDataset(unittest.TestCase):
    def test_builtin_shapes(self):
        for kind in ("moons", "circles", "xor"):
            X, y = build_dataset(kind, 200, 0.1, 42, [])
            self.assertEqual(X.shape, (200, 2))
            self.assertEqual(y.shape, (200,))
            self.assertEqual(set(np.unique(y).tolist()), {0, 1})
            self.assertEqual(X.dtype, np.float32)

    def test_custom_requires_two_classes(self):
        pts = [{"x": 0.0, "y": 0.0, "label": 0}] * 5
        with self.assertRaises(ValueError):
            build_dataset("custom", 200, 0.1, 42, pts)
        pts[0] = {"x": 1.0, "y": 1.0, "label": 1}
        X, y = build_dataset("custom", 200, 0.1, 42, pts)
        self.assertEqual(X.shape, (5, 2))

    def test_grid_top_row_is_y_max(self):
        X, _ = build_dataset("moons", 200, 0.1, 42, [])
        grid, meta = make_grid(X, 32)
        self.assertEqual(grid.shape, (32 * 32, 2))
        self.assertAlmostEqual(float(grid[0, 1]), meta["y_max"], places=4)
        px, py = world_to_pixel(meta["x_min"], meta["y_max"], meta, 480, 480)
        self.assertAlmostEqual(px, 0.0)
        self.assertAlmostEqual(py, 0.0)


class TestNetworks(unittest.TestCase):
    def test_forward_shape(self):
        models = build_all(13)
        for tag, model in models.items():
            out = model(torch.zeros(7, 2))
            self.assertEqual(tuple(out.shape), (7, 2), f"model {tag}")

    def test_reproducible_initialization(self):
        a = build_all(13)
        b = build_all(13)
        for tag in a:
            for pa, pb in zip(a[tag].parameters(), b[tag].parameters()):
                self.assertTrue(torch.equal(pa, pb), f"model {tag} not reproducible")

    def test_catalog_param_counts(self):
        cat = {c["tag"]: c for c in network_catalog()}
        self.assertEqual(cat["A"]["params"], 52)
        self.assertEqual(cat["D"]["params"], 27)
        self.assertEqual(cat["F"]["params"], 354)
        self.assertEqual(cat["C"]["activation"], "ReLU")


class TestTrainingPipeline(unittest.TestCase):
    def test_short_run_emits_events_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            cfg = ExperimentConfig(network="D", epochs=60,
                                   frame_every=10, grid_size=24)
            hub = FakeHub()
            store.create_experiment("t1", cfg, "unit test")
            run_training("t1", cfg, hub, None, store, NETWORK_CATALOG)

            types = [e["type"] for e in hub.events]
            self.assertEqual(types[0], "meta")
            self.assertEqual(types[-1], "done")
            self.assertEqual(sum(1 for t in types if t == "metric"), 60)
            self.assertGreaterEqual(sum(1 for t in types if t == "frame"), 6)

            exp = store.get_experiment("t1")
            self.assertEqual(exp["status"], "done")
            self.assertEqual(len(exp["metrics"]), 60)
            self.assertGreaterEqual(len(exp["frames"]), 6)
            self.assertEqual(len(exp["frames"][0]["probs"]) % 4, 0)
            self.assertLess(exp["metrics"][-1]["loss"],
                            exp["metrics"][0]["loss"])
            self.assertIsNotNone(exp["grid_meta"])

    def test_linear_model_stays_linear(self):
        """A 号无激活，即使训练后 loss 也不该降到接近 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            cfg = ExperimentConfig(network="A", epochs=200,
                                   frame_every=50, grid_size=16)
            store.create_experiment("t2", cfg, "linear")
            hub = FakeHub()
            run_training("t2", cfg, hub, None, store, NETWORK_CATALOG)
            done = [e for e in hub.events if e["type"] == "done"][0]
            self.assertGreater(done["final_loss"], 0.2)
            self.assertLess(done["final_acc"], 0.95)


if __name__ == "__main__":
    unittest.main(verbosity=2)
