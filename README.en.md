<div align="center">

# Backprop Lab

**Turn the internal state of a BP training run into a scrubbable, replayable, comparable timeline.**

[中文](./README.md) · [API](#api) · [Deployment](#deployment)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C?logo=pytorch&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue)

</div>

![UI preview: decision boundary, loss curve and activation heatmap of network C](./docs/preview.png)

---

## The problem

Neural-network visualizations are everywhere, but almost all of them show **one static decision boundary after training**. They cannot answer the interesting questions: *why is a 5-layer linear stack still a straight line? At which epoch did ReLU start bending the boundary? Did half the neurons in network D die?*

Backprop Lab treats the training process itself as a first-class object. During the PyTorch loop, the backend collects per-epoch loss, accuracy, gradient norm, per-layer activations, and a 48×48 decision-probability grid, then streams everything over WebSocket. The frontend caches it as a timeline you can scrub back to epoch 37 and watch a straight line slowly fold into a moon-shaped boundary.

It is also a portfolio project you can actually defend in an interview: instead of saying "I tuned a model", you can demonstrate why stacked `Linear` layers collapse into one linear transform, why ReLU introduces piecewise linearity, why 5 hidden neurons underfit, and how a repeated seed causes dead ReLUs.

## Features

| | |
| --- | --- |
| **4 datasets** | `make_moons`, concentric circles, XOR, and **freehand Canvas drawing** (left click = red class, right click = blue) |
| **6 networks** | A–F `nn.Sequential` variants: no activation, deep-linear, ReLU, Sigmoid, two hidden layers |
| **Live stream** | Per-epoch WebSocket events: loss / acc / grad norm / ReLU zero-activation rate / layer activations |
| **Timeline replay** | Scrubbable and playable decision-boundary keyframes — watch straight → kinked → curved |
| **Diagnostics** | Overlaid loss curves, activation heatmap, automatic hints for dead ReLU and vanishing gradients |
| **Snapshots** | Everything persisted in SQLite; `?exp=<id>` replays an experiment without retraining |
| **Instant demo** | `?auto=1&net=C` starts a run on page load — handy for GIFs and live demos |

## Quick start

```bash
git clone https://github.com/anshu-lgtm/backprop-lab.git
cd backprop-lab

python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python run.py
```

Open `http://127.0.0.1:8000` (auto-opened), Swagger docs at `/docs`. Use `PORT=8765 python run.py` for a different port, `--no-browser` to disable auto-open.

> **Zero-build frontend.** Plain HTML/CSS/JS + Canvas served by FastAPI `StaticFiles`. No `npm install`, no bundler — one command from clone to running app.

## Benchmark results

`make_moons(n_samples=200, noise=0.1, random_state=42)`, `CrossEntropyLoss + Adam(lr=0.1)`, 1000 epochs, global seed 13, networks created in A→F order.

| Net | Shape | Activation | Final loss | Accuracy | Boundary |
| --- | --- | --- | --- | --- | --- |
| A | 2-10-2 | none | 0.2721 | 86.5% | straight line |
| B | 2-20-5-30-5-2 | none | 0.2721 | 86.5% | still a straight line |
| C | 2-20-5-30-5-2 | ReLU | 0.0000 | 100% | perfect separation |
| D | 2-5-2 | ReLU | 0.2285 | 89.0% | kinked, underfitting |
| E | 2-5-2 | Sigmoid | 0.0006 | 100% | smooth curve |
| F | 2-16-16-2 | ReLU ×2 | 0.0000 | 100% | smooth curve |

Three comparisons carry the whole project: **A vs B** (composing `Linear` layers still yields one linear map `W = W₂W₁`), **B vs C** (a single `nn.ReLU()` enables piecewise-linear boundaries), **D vs E** (too few hidden neurons underfit; Sigmoid is smooth but converges slower).

## Architecture

```mermaid
flowchart LR
    subgraph Browser["Browser · zero-build frontend"]
        UI["Canvas dataset / network picker"]
        TL["Timeline replay"]
        CH["Loss curve · activation heatmap"]
    end
    subgraph Server["FastAPI single process"]
        REST["REST /api/*"]
        WS["WebSocket /ws/experiments/id"]
        HUB["Hub event bus<br/>with history cache"]
        TH["Training thread<br/>PyTorch + forward hooks"]
        DB[("SQLite<br/>snapshots")]
    end
    UI -->|"POST /api/experiments"| REST
    REST -->|"spawn background task"| TH
    TH -->|"call_soon_threadsafe"| HUB
    HUB --> WS
    WS -->|"meta / metric / frame / done"| TL
    WS -->|"metric / frame"| CH
    HUB --> DB
    REST -->|"GET /api/experiments/id"| DB
    DB -.->|"?exp=id replay"| TL
```

### Implementation highlights

1. **Thread ↔ event loop bridge.** Training runs in a dedicated thread; events are posted back to the asyncio loop with `loop.call_soon_threadsafe` and broadcast by the Hub. The Hub keeps a history buffer, so late subscribers, page refreshes and multiple tabs never miss data.
2. **Boundaries are probability grids, not screenshots.** Each keyframe computes `P(class=1)` on a 48×48 grid, quantizes it to `uint8`, stores it as a BLOB and sends it as base64 (~2.3 KB/frame). The frontend upscales via `ImageData`, producing smooth confidence gradients instead of hard class blocks. One frame every 20 epochs, auto-thinned to at most 200 frames ≈ 150 KB for a 1000-epoch run.
3. **Quantifying dead ReLUs.** `register_forward_hook` captures activation outputs; the zero-activation ratio is measured per epoch and persisted. "Half of network D died" becomes a measurable curve.
4. **Reproducibility has a real cost here.** `torch.manual_seed(13)` is set exactly once and the RNG advances naturally as networks A→F are created. An earlier version reseeded before *each* network — network D's ReLUs then output nothing but zeros, loss stuck at 0.6931 and accuracy at 50%. Two unit tests lock this behaviour down.

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/networks` | Catalog of networks A–F |
| `GET` | `/api/datasets/{kind}?n_samples=200&noise=0.1` | Dataset preview points + grid metadata |
| `POST` | `/api/experiments` | Create experiment and start background training |
| `GET` | `/api/experiments?limit=50` | Experiment list |
| `GET` | `/api/experiments/{id}` | Full snapshot (metrics / frames / activations) for replay |
| `WS` | `/ws/experiments/{id}` | Streaming events |

```json
{
  "network": "C",
  "dataset": "moons",
  "n_samples": 200,
  "noise": 0.1,
  "epochs": 1000,
  "lr": 0.1,
  "seed": 13,
  "data_seed": 42,
  "frame_every": 20,
  "grid_size": 48,
  "name": "Network C · perfect separation"
}
```

WebSocket sequence: `meta` → `metric` × N (one per epoch) → `frame` (interleaved with metrics) → `done` / `error`.

SQLite tables (generated at `data/lab.sqlite3`, gitignored): `experiments`, `metrics` `(exp_id, epoch)`, `frames` `(exp_id, epoch)`, `activations` `(exp_id, epoch)`. Metrics are flushed in batches of 100.

## Tests

```bash
python -m unittest discover -s tests -v
```

8 unit tests: dataset shapes, two-class validation for custom data, grid orientation, forward shapes, reproducible initialization, parameter counts, short-run event/persistence pipeline, linear-model boundary stays linear.

The CI config lives at `docs/ci.yml.example`: create `.github/workflows/ci.yml` in the GitHub web UI and paste its contents to enable automated tests on every push/PR (CI installs CPU-only torch first to avoid multi-GB CUDA wheels).

> Note: GitHub requires the `workflow` scope on a Personal Access Token to create or modify files under `.github/workflows/`; the publishing token only had `repo`, so the config ships as an example file. Creating the file once in the web UI enables CI without issuing a new token. With a `workflow`-scoped token you can also just `cp docs/ci.yml.example .github/workflows/ci.yml` and commit locally.

## Deployment

> This is a dynamic FastAPI app, **not** a static site — GitHub Pages cannot host it. An online demo needs a Python-capable host.

```bash
docker build -t backprop-lab .
docker run -p 8000:8000 backprop-lab
```

`run.py` binds `127.0.0.1` by default; inside a container set `HOST=0.0.0.0` (the Dockerfile does this). When reverse-proxying, allow WebSocket upgrade (Nginx: `proxy_set_header Upgrade $http_upgrade;` + `Connection "upgrade"`). Training is an in-process thread, so the app is a stateful single instance — multi-replica deployments should swap the Hub for Redis Pub/Sub and move training to Celery/RQ. Mount a volume for SQLite or snapshots vanish on restart.

## Roadmap

- [ ] Drag-and-drop layer builder
- [ ] Shareable experiment links with auth
- [ ] PDF experiment report export
- [ ] React + TS + Vite frontend (backend unchanged)
- [ ] Side-by-side comparison view and Celery-based concurrent training

## License

[MIT](./LICENSE) © 2026 Backprop Lab contributors
