'use strict';

const $ = id => document.getElementById(id);
const COLORS = ['#1f4e8d', '#d85a30', '#1d9e75', '#b07b28', '#7a5cc4', '#c05a92'];
const CUSTOM_GRID = { x_min: -1.5, x_max: 2.5, y_min: -1.0, y_max: 1.5 };

const S = {
  id: null, ws: null, meta: null, points: null, grid: null,
  metrics: [], frames: new Map(), frameEpochs: [],
  current: 0, follow: true, playing: false, finished: false, timer: null,
  network: 'D', catalog: [], curves: [], drawPoints: [], renderPending: false,
};

function setStatus(kind, text) {
  const b = $('statusBadge');
  b.className = 'badge' + (kind === 'ready' ? '' : ' ' + kind);
  b.textContent = text;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function decodeFrame(b64) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

function mix(a, b, t) {
  return [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * t));
}

function worldToPx(x, y, g, W, H) {
  return [(x - g.x_min) / (g.x_max - g.x_min) * W,
          (g.y_max - y) / (g.y_max - g.y_min) * H];
}

function drawDot(ctx, px, py, label) {
  ctx.beginPath();
  ctx.arc(px, py, 4.1, 0, Math.PI * 2);
  ctx.fillStyle = label === 1 ? '#3a7bd5' : '#d85a30';
  ctx.fill();
  ctx.lineWidth = 1;
  ctx.strokeStyle = 'rgba(255,255,255,.9)';
  ctx.stroke();
}

/* ---------------- 网络目录 ---------------- */

function renderNetworks() {
  $('networkList').innerHTML = S.catalog.map(n => `
    <div class="netitem ${n.tag === S.network ? 'on' : ''}" data-tag="${n.tag}">
      <div class="nettag">${n.tag}</div>
      <div class="nettext">
        <b>${escapeHtml(n.name)} · ${escapeHtml(n.activation)}</b>
        <span>${escapeHtml(n.shape)} · ${n.params} params</span>
        <em>${escapeHtml(n.note)}</em>
      </div>
    </div>`).join('');
  document.querySelectorAll('.netitem').forEach(el => {
    el.onclick = () => {
      S.network = el.dataset.tag;
      renderNetworks();
      const info = S.catalog.find(n => n.tag === S.network);
      if (info) $('boundaryNote').textContent =
        `${info.tag} 号 · ${info.shape} · 激活 ${info.activation}`;
    };
  });
}

async function loadCatalog() {
  try {
    const r = await fetch('/api/networks');
    S.catalog = (await r.json()).networks;
    renderNetworks();
  } catch (e) {
    $('networkList').innerHTML = '<div class="hint">网络目录加载失败，请确认后端已启动</div>';
  }
}

/* ---------------- 数据集预览 / 手绘 ---------------- */

async function preview() {
  const kind = $('dataset').value;
  $('drawWrap').classList.toggle('hidden', kind !== 'custom');
  const q = new URLSearchParams({
    n_samples: $('nSamples').value, noise: $('noise').value, data_seed: '42',
  });
  try {
    const r = await fetch(`/api/datasets/${kind}?${q}`);
    const d = await r.json();
    S.grid = d.grid;
    S.points = kind === 'custom'
      ? { x: S.drawPoints.map(p => p.x), y: S.drawPoints.map(p => p.y),
          label: S.drawPoints.map(p => p.label) }
      : d.points;
    drawDrawCanvas();
    drawBoundary();
  } catch (e) {
    console.warn('preview failed', e);
  }
}

function drawDrawCanvas() {
  const c = $('drawCanvas'), ctx = c.getContext('2d'), w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#fbfcfe';
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#e8edf4';
  ctx.lineWidth = 1;
  for (let i = 1; i < 6; i++) {
    ctx.beginPath(); ctx.moveTo(w * i / 6, 0); ctx.lineTo(w * i / 6, h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, h * i / 6); ctx.lineTo(w, h * i / 6); ctx.stroke();
  }
  S.drawPoints.forEach(p => {
    const [px, py] = worldToPx(p.x, p.y, CUSTOM_GRID, w, h);
    drawDot(ctx, px, py, p.label);
  });
  if (!S.drawPoints.length) {
    ctx.fillStyle = '#9aa7b8';
    ctx.font = '12px "Microsoft YaHei"';
    ctx.textAlign = 'center';
    ctx.fillText('在这里点出两类样本', w / 2, h / 2);
  }
}

function bindDrawCanvas() {
  const c = $('drawCanvas');
  c.addEventListener('contextmenu', e => e.preventDefault());
  c.addEventListener('mousedown', e => {
    e.preventDefault();
    const rect = c.getBoundingClientRect();
    const px = (e.clientX - rect.left) * c.width / rect.width;
    const py = (e.clientY - rect.top) * c.height / rect.height;
    const x = CUSTOM_GRID.x_min + px / c.width * (CUSTOM_GRID.x_max - CUSTOM_GRID.x_min);
    const y = CUSTOM_GRID.y_max - py / c.height * (CUSTOM_GRID.y_max - CUSTOM_GRID.y_min);
    S.drawPoints.push({ x: +x.toFixed(4), y: +y.toFixed(4), label: e.button === 2 ? 1 : 0 });
    drawDrawCanvas();
    if ($('dataset').value === 'custom') {
      S.points = { x: S.drawPoints.map(p => p.x), y: S.drawPoints.map(p => p.y),
                   label: S.drawPoints.map(p => p.label) };
      drawBoundary();
    }
  });
  $('clearDraw').onclick = () => { S.drawPoints = []; drawDrawCanvas(); preview(); };
}

/* ---------------- 训练与 WebSocket ---------------- */

function resetRun() {
  S.metrics = [];
  S.frames = new Map();
  S.frameEpochs = [];
  S.current = 0;
  S.follow = true;
  S.finished = false;
  S.meta = null;
  S.curves.forEach(c => { c.active = false; });
  stopPlay();
  $('timeline').max = 0;
  $('timeline').value = 0;
  $('lossNote').textContent = '—';
  if (S.ws) { S.ws.onclose = null; S.ws.close(); S.ws = null; }
}

async function start() {
  const cfg = {
    network: S.network,
    dataset: $('dataset').value,
    n_samples: +$('nSamples').value,
    noise: +$('noise').value,
    epochs: +$('epochs').value,
    lr: +$('lr').value,
    seed: 13,
    data_seed: 42,
    frame_every: +$('frameEvery').value,
    grid_size: 48,
    points: S.drawPoints.map(p => ({ x: p.x, y: p.y, label: p.label })),
  };
  resetRun();
  setStatus('running', '训练中…');
  $('startBtn').disabled = true;
  try {
    const r = await fetch('/api/experiments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || `HTTP ${r.status}`);
    }
    const d = await r.json();
    S.id = d.id;
    S.curves.push({
      key: d.id, label: `${cfg.network} 号 · ${cfg.dataset}`, losses: [],
      color: COLORS[S.curves.length % COLORS.length], active: true,
    });
    connect(d.id);
  } catch (e) {
    setStatus('error', '启动失败');
    $('startBtn').disabled = false;
    $('insight').textContent = `启动失败：${e.message}`;
  }
}

function connect(id) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/experiments/${id}`);
  S.ws = ws;
  ws.onmessage = e => {
    try { handle(JSON.parse(e.data)); } catch (err) { console.error(err); }
  };
  ws.onclose = () => {
    if (!S.finished) setStatus('error', '连接断开');
    $('startBtn').disabled = false;
  };
  ws.onerror = () => setStatus('error', '连接错误');
}

function handle(ev) {
  if (ev.type === 'meta') {
    S.meta = ev;
    S.points = ev.points;
    S.grid = ev.grid;
    $('timeline').max = Math.max(0, ev.epochs - 1);
    $('timeline').value = 0;
    $('boundaryNote').textContent =
      `${ev.network} 号 · ${ev.network_info.shape} · 激活 ${ev.network_info.activation}`;
  } else if (ev.type === 'metric') {
    S.metrics.push(ev);
    const cv = S.curves.find(c => c.key === S.id);
    if (cv) cv.losses.push(ev.loss);
    if (S.follow) S.current = ev.epoch;
  } else if (ev.type === 'frame') {
    S.frames.set(ev.epoch, decodeFrame(ev.data));
    S.frameEpochs = [...S.frames.keys()].sort((a, b) => a - b);
  } else if (ev.type === 'done') {
    S.finished = true;
    setStatus('done', `完成 · loss ${ev.final_loss.toFixed(4)} · ${ev.elapsed}s`);
    $('startBtn').disabled = false;
    $('lossNote').textContent =
      `最终 ${ev.final_loss.toFixed(4)} / 准确率 ${(ev.final_acc * 100).toFixed(1)}%`;
    loadHistory();
  } else if (ev.type === 'error') {
    S.finished = true;
    setStatus('error', '训练出错');
    $('startBtn').disabled = false;
    $('insight').textContent = ev.message;
  }
  scheduleRender();
}

function scheduleRender() {
  if (S.renderPending) return;
  S.renderPending = true;
  requestAnimationFrame(() => { S.renderPending = false; renderAll(); });
}

function renderAll() {
  const ep = S.current;
  const total = S.meta ? S.meta.epochs : 0;
  $('timeline').value = ep;
  $('epochLabel').textContent = `${ep} / ${Math.max(0, total - 1)}`;
  const m = S.metrics[ep];
  $('mEpoch').textContent = m ? ep : '—';
  $('mLoss').textContent = m ? m.loss.toFixed(4) : '—';
  $('mAcc').textContent = m ? (m.acc * 100).toFixed(1) + '%' : '—';
  $('mDead').textContent = m ? (m.dead_ratio * 100).toFixed(1) + '%' : '—';
  drawBoundary();
  drawLoss();
  drawActivation(m);
  updateInsight(m);
}

function stopPlay() {
  S.playing = false;
  $('playBtn').textContent = '▶';
  if (S.timer) { clearInterval(S.timer); S.timer = null; }
}

function togglePlay() {
  if (S.playing) { stopPlay(); return; }
  if (!S.meta) return;
  S.playing = true;
  S.follow = false;
  $('playBtn').textContent = '❚❚';
  const step = Math.max(1, Math.round(S.meta.epochs / 180));
  S.timer = setInterval(() => {
    S.current = Math.min(S.current + step, S.meta.epochs - 1);
    scheduleRender();
    if (S.current >= S.meta.epochs - 1) stopPlay();
  }, 50);
}

/* ---------------- 可视化绘制 ---------------- */

function probColor(t) {
  const s = Math.abs(t - 0.5) * 2;
  const base = [250, 251, 253];
  const target = t < 0.5 ? [216, 110, 88] : [70, 130, 210];
  return mix(base, target, 0.12 + 0.5 * s);
}

function nearestFrame(ep) {
  if (!S.frameEpochs.length) return null;
  let best = null;
  for (const f of S.frameEpochs) {
    if (f <= ep) best = f; else break;
  }
  if (best === null) best = S.frameEpochs[0];
  return S.frames.get(best) || null;
}

function drawBoundary() {
  const c = $('boundary'), ctx = c.getContext('2d'), W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#fbfcfe';
  ctx.fillRect(0, 0, W, H);
  const g = S.grid;
  if (!g) return;

  const frame = nearestFrame(S.current);
  if (frame) {
    const w = (S.grid.width || 48), h = (S.grid.height || 48);
    const off = document.createElement('canvas');
    off.width = w; off.height = h;
    const octx = off.getContext('2d');
    const img = octx.createImageData(w, h);
    for (let i = 0; i < w * h; i++) {
      const col = probColor(frame[i] / 255);
      img.data[i * 4] = col[0];
      img.data[i * 4 + 1] = col[1];
      img.data[i * 4 + 2] = col[2];
      img.data[i * 4 + 3] = 255;
    }
    octx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(off, 0, 0, W, H);
  }

  ctx.strokeStyle = 'rgba(120,140,165,.10)';
  ctx.lineWidth = 1;
  for (let i = 1; i < 8; i++) {
    ctx.beginPath(); ctx.moveTo(W * i / 8, 0); ctx.lineTo(W * i / 8, H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, H * i / 8); ctx.lineTo(W, H * i / 8); ctx.stroke();
  }

  const pts = S.points;
  if (pts && pts.x) {
    for (let i = 0; i < pts.x.length; i++) {
      const [px, py] = worldToPx(pts.x[i], pts.y[i], g, W, H);
      drawDot(ctx, px, py, pts.label[i]);
    }
  }
  if (!frame) {
    ctx.fillStyle = '#8a97a8';
    ctx.font = '13px "Microsoft YaHei"';
    ctx.textAlign = 'center';
    ctx.fillText('等待决策边界关键帧…', W / 2, H / 2);
  }
}

function drawLoss() {
  const c = $('lossChart'), ctx = c.getContext('2d'), W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  const P = { l: 46, r: 12, t: 18, b: 30 };
  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const curves = S.curves.filter(x => x.losses.length > 0);
  let maxY = 0.8, maxX = 1;
  curves.forEach(cv => {
    if (cv.losses.length > maxX) maxX = cv.losses.length;
    for (const v of cv.losses) if (v > maxY) maxY = Math.ceil(v * 10) / 10;
  });
  ctx.strokeStyle = '#e8edf4';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#8a97a8';
  ctx.font = '11px Consolas';
  for (let i = 0; i <= 4; i++) {
    const y = P.t + ih * (1 - i / 4);
    ctx.beginPath(); ctx.moveTo(P.l, y); ctx.lineTo(W - P.r, y); ctx.stroke();
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    ctx.fillText((maxY * i / 4).toFixed(2), P.l - 7, y);
  }
  for (let i = 0; i <= 4; i++) {
    const x = P.l + iw * i / 4;
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(String(Math.round(maxX * i / 4)), x, H - P.b + 6);
  }
  ctx.fillStyle = '#6b7787';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText('loss', 8, 4);

  curves.forEach(cv => {
    ctx.beginPath();
    for (let i = 0; i < cv.losses.length; i++) {
      const x = P.l + iw * (i / Math.max(1, maxX - 1));
      const y = P.t + ih * (1 - Math.min(cv.losses[i], maxY) / maxY);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = cv.color;
    ctx.lineWidth = cv.active ? 2 : 1.3;
    ctx.globalAlpha = cv.active ? 1 : 0.55;
    ctx.stroke();
    ctx.globalAlpha = 1;
  });

  if (S.meta) {
    const x = P.l + iw * (S.current / Math.max(1, maxX - 1));
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = '#1f4e8d';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, P.t); ctx.lineTo(x, P.t + ih); ctx.stroke();
    ctx.setLineDash([]);
  }
  $('curveLegend').innerHTML = curves.map(cv =>
    `<span><i style="background:${cv.color}"></i>${escapeHtml(cv.label)}${cv.active ? ' (当前)' : ''}</span>`
  ).join('');
}

function drawActivation(m) {
  const c = $('activation'), ctx = c.getContext('2d'), W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  const acts = (m && m.activations) ? m.activations : [];
  if (!acts.length) {
    ctx.fillStyle = '#f3f6fa';
    ctx.fillRect(16, 20, W - 32, 92);
    ctx.fillStyle = '#6b7787';
    ctx.font = '12px "Microsoft YaHei"';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const noAct = S.meta && (S.meta.network === 'A' || S.meta.network === 'B');
    ctx.fillText(noAct ? '该网络没有激活层：多层 Linear 复合后仍是线性变换' : '等待激活数据…', W / 2, 66);
    return;
  }
  let x = 18, y = 34;
  const cell = 22, gap = 4;
  ctx.font = '10px Consolas';
  for (const layer of acts) {
    if (y > H - 26) break;
    ctx.fillStyle = '#1f4e8d';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`L${layer.layer} ${layer.kind} · ${layer.values.length} units`, 18, y - 14);
    for (const raw of layer.values) {
      const v = Number(raw);
      const t = Math.max(0, Math.min(1, v));
      const col = mix([235, 242, 250], [31, 78, 141], 0.10 + 0.85 * t);
      ctx.fillStyle = `rgb(${col[0]},${col[1]},${col[2]})`;
      ctx.fillRect(x, y, cell, cell);
      ctx.strokeStyle = 'rgba(255,255,255,.55)';
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 0.5, y + 0.5, cell - 1, cell - 1);
      if (layer.values.length <= 16) {
        ctx.fillStyle = t > 0.55 ? '#fff' : '#44536a';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(v.toFixed(1), x + cell / 2, y + cell / 2);
      }
      x += cell + gap;
      if (x + cell > W - 14) { x = 18; y += cell + gap; }
    }
    x = 18;
    y += cell + gap + 16;
  }
}

function updateInsight(m) {
  let txt = '等待训练数据…';
  if (S.meta) {
    txt = `【${S.meta.network} 号】${S.meta.network_info.note}。`;
    if (!m) {
      txt += ' 拖动时间轴可回到任意一轮查看边界。';
    } else if (m.dead_ratio > 0.9) {
      txt += ` 当前 ${(m.dead_ratio * 100).toFixed(0)}% 的 ReLU 输出为 0 —— 这就是「神经元死亡」，梯度回不来，loss 会卡住。`;
    } else if (m.grad_norm < 1e-4) {
      txt += ` 梯度范数 ${m.grad_norm.toExponential(1)} 已接近 0，参数几乎不再更新（梯度消失）。`;
    } else if (m.loss < 0.01) {
      txt += ` loss 已降到 ${m.loss.toFixed(4)}，两类样本基本被分开了。`;
    } else {
      txt += ` 当前 loss ${m.loss.toFixed(4)}、梯度范数 ${m.grad_norm.toFixed(3)}，训练仍在进行。`;
    }
  }
  $('insight').textContent = txt;
}

/* ---------------- 历史对比 ---------------- */

async function loadHistory() {
  try {
    const r = await fetch('/api/experiments?limit=12');
    const d = await r.json();
    $('historyList').innerHTML = d.experiments.length
      ? d.experiments.map(e => `
          <div class="histitem" data-id="${e.id}">
            <b>${escapeHtml(e.name)}</b>
            <span>${e.status === 'done' && e.final_loss != null
              ? Number(e.final_loss).toFixed(4) : escapeHtml(e.status)}</span>
          </div>`).join('')
      : '<div class="hint">暂无历史实验</div>';
    document.querySelectorAll('.histitem').forEach(el => {
      el.onclick = () => addCurve(el.dataset.id);
    });
  } catch (e) { console.warn('history failed', e); }
}

async function addCurve(id) {
  if (S.curves.some(c => c.key === id)) return;
  try {
    const r = await fetch(`/api/experiments/${id}`);
    const d = await r.json();
    const losses = (d.metrics || []).map(x => x.loss);
    if (!losses.length) return;
    S.curves.push({
      key: id, label: `${d.network} 号 · ${d.dataset}`, losses,
      color: COLORS[S.curves.length % COLORS.length], active: false,
    });
    scheduleRender();
  } catch (e) { console.warn('addCurve failed', e); }
}

async function loadSnapshot(id) {
  try {
    setStatus('running', '载入快照…');
    const r = await fetch(`/api/experiments/${id}`);
    if (!r.ok) throw new Error('快照不存在或已被删除');
    const d = await r.json();
    const cfg = d.config || {};
    resetRun();
    S.id = id;
    S.finished = true;
    S.follow = false;
    S.network = d.network;
    renderNetworks();
    S.grid = d.grid_meta;
    const info = S.catalog.find(n => n.tag === d.network) || {};
    S.meta = {
      exp_id: id, network: d.network, network_info: info,
      dataset: d.dataset, epochs: d.epochs, lr: d.lr, seed: d.seed,
      frame_every: cfg.frame_every || 20, grid: d.grid_meta, points: null,
    };

    let pts = { x: [], y: [], label: [] };
    if (d.dataset === 'custom') {
      const ps = cfg.points || [];
      pts = { x: ps.map(p => p.x), y: ps.map(p => p.y),
              label: ps.map(p => p.label) };
    } else {
      const q = new URLSearchParams({
        n_samples: cfg.n_samples || 200,
        noise: cfg.noise != null ? cfg.noise : 0.1,
        data_seed: cfg.data_seed != null ? cfg.data_seed : 42,
      });
      const pr = await fetch(`/api/datasets/${d.dataset}?${q}`);
      pts = (await pr.json()).points;
    }
    S.points = pts;
    S.meta.points = pts;
    S.metrics = d.metrics || [];
    S.frames = new Map();
    (d.frames || []).forEach(f => S.frames.set(f.epoch, decodeFrame(f.probs)));
    S.frameEpochs = [...S.frames.keys()].sort((a, b) => a - b);
    S.current = Math.max(0, S.metrics.length - 1);

    S.curves.push({
      key: id, label: `${d.network} 号 · ${d.dataset}（快照）`,
      losses: S.metrics.map(m => m.loss),
      color: COLORS[S.curves.length % COLORS.length], active: true,
    });
    $('timeline').max = Math.max(0, d.epochs - 1);
    $('boundaryNote').textContent = `${d.network} 号 · ${info.shape || ''} · 快照回放`;
    $('lossNote').textContent = d.final_loss != null
      ? `快照 · 最终 ${Number(d.final_loss).toFixed(4)} / 准确率 ${(Number(d.final_acc) * 100).toFixed(1)}%`
      : '快照回放';
    setStatus('done', '快照回放');
    renderAll();
  } catch (e) {
    setStatus('error', '载入失败');
    $('insight').textContent = `快照载入失败：${e.message}`;
  }
}

/* ---------------- 初始化 ---------------- */

function bindControls() {
  const pairs = [
    ['nSamples', 'nSamplesVal', v => v],
    ['noise', 'noiseVal', v => (+v).toFixed(2)],
    ['epochs', 'epochsVal', v => v],
    ['lr', 'lrVal', v => (+v).toFixed(3)],
    ['frameEvery', 'frameEveryVal', v => v],
  ];
  pairs.forEach(([id, out, fmt]) => {
    $(id).addEventListener('input', () => { $(out).textContent = fmt($(id).value); });
  });
  $('nSamples').addEventListener('change', preview);
  $('noise').addEventListener('change', preview);
  $('dataset').addEventListener('change', preview);
  $('startBtn').onclick = start;
  $('playBtn').onclick = togglePlay;
  $('timeline').oninput = e => {
    S.follow = false;
    S.current = +e.target.value;
    stopPlay();
    scheduleRender();
  };
  bindDrawCanvas();
}

async function init() {
  bindControls();
  await loadCatalog();
  await preview();
  await loadHistory();
  const info = S.catalog.find(n => n.tag === S.network);
  if (info) $('boundaryNote').textContent =
    `${info.tag} 号 · ${info.shape} · 激活 ${info.activation}`;
  setStatus('ready', '就绪');

  // 分享链接：?exp=<id> 直接回放已完成实验；?auto=1&net=C 打开即自动跑一次
  const params = new URLSearchParams(location.search);
  if (params.get('exp')) {
    await loadSnapshot(params.get('exp'));
  } else if (params.get('auto') === '1') {
    const wanted = (params.get('net') || '').toUpperCase();
    if (S.catalog.some(n => n.tag === wanted)) {
      S.network = wanted;
      renderNetworks();
    }
    setTimeout(start, 300);
  }
}

init();
