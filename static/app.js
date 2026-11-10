/* Short Creator front end: home, project and clip-editor views. */
const $app = document.getElementById('app');
const $crumbs = document.getElementById('crumbs');
let cleanup = [];     // functions to run when leaving a view
let META = { fonts: ['Arial Black'] };

// ---------------------------------------------------------------- helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'style') el.style.cssText = v;
    else if (k in el && k !== 'list') el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}
async function api(path, opts = {}) {
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { 'Content-Type': 'application/json' };
  }
  const r = await fetch('/api' + path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), 3200);
}
function fmt(t, dec = 0) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  return m + ':' + (dec ? s.toFixed(dec).padStart(3 + dec, '0') : String(Math.floor(s)).padStart(2, '0'));
}
function every(ms, fn) {
  let stop = false;
  (async function loop() {
    while (!stop) {
      try { await fn(); } catch (e) { console.warn(e); }
      await new Promise(r => setTimeout(r, ms));
    }
  })();
  cleanup.push(() => { stop = true; });
}
function prefs(set) {
  try {
    if (set) localStorage.setItem('sc-prefs', JSON.stringify(set));
    return JSON.parse(localStorage.getItem('sc-prefs') || '{}');
  } catch (e) { return set || {}; }
}
function crumbs(...items) {
  $crumbs.replaceChildren(...items.flatMap((it, i) => [
    h('span', {}, '/'),
    i === items.length - 1 ? h('span', { class: 'cur' }, it[0]) : h('a', { href: it[1] }, it[0]),
  ]));
}
const STAGES = { queued: 'Starting', downloading: 'Downloading video', preparing: 'Preparing video',
  transcribing: 'Transcribing speech', picking: 'Finding the best moments' };

// ---------------------------------------------------------------- router
async function route() {
  cleanup.forEach(f => f()); cleanup = [];
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  try {
    if (parts[0] === 'p' && parts[2] === 'c') await editorView(parts[1], parts[3]);
    else if (parts[0] === 'p') await projectView(parts[1]);
    else await homeView();
  } catch (e) {
    $app.replaceChildren(h('div', { class: 'card stage' }, h('p', {}, e.message), h('a', { class: 'btn', href: '#/' }, 'Back to home')));
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);

// ---------------------------------------------------------------- home
async function homeView() {
  crumbs();
  const p = Object.assign({ len: '30-60', count: '0', framing: 'crop', subtitles: true }, prefs());
  let tab = 'link';
  const url = h('input', { type: 'url', placeholder: 'Paste a video link (YouTube, Vimeo, TikTok, X, ...)', class: 'grow' });
  const file = h('input', { type: 'file', accept: 'video/*,.mkv,.mov,.avi,.webm', style: 'display:none' });
  const sel = (key, options) => h('select', { onchange: e => { p[key] = e.target.value; prefs(p); } },
    options.map(([v, label]) => h('option', { value: v, selected: String(p[key]) === v }, label)));
  const settings = () => {
    const [a, b] = p.len.split('-').map(Number);
    return { min_len: a, max_len: b, max_clips: Number(p.count), framing: p.framing, subtitles: p.subtitles !== 'off' && p.subtitles !== false };
  };
  const go = h('button', { class: 'primary', onclick: fromUrl }, 'Create shorts');
  async function fromUrl() {
    if (!url.value.trim()) return toast('Paste a video link first');
    go.disabled = true;
    try {
      const pr = await api('/projects/url', { method: 'POST', json: { url: url.value.trim(), settings: settings() } });
      location.hash = '#/p/' + pr.id;
    } catch (e) { toast(e.message); go.disabled = false; }
  }
  url.addEventListener('keydown', e => { if (e.key === 'Enter') fromUrl(); });
  const drop = h('div', { class: 'drop', onclick: () => file.click() },
    h('div', { style: 'font-size:28px' }, '⬆'), h('div', {}, 'Drop a video here, or click to choose a file'));
  function upload(f) {
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f); fd.append('settings', JSON.stringify(settings()));
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/projects/upload');
    xhr.upload.onprogress = e => { drop.replaceChildren(h('div', {}, `Uploading ${f.name} - ${Math.round(e.loaded / e.total * 100)}%`),
      h('div', { class: 'bar', style: 'margin-top:10px' }, h('i', { style: `width:${e.loaded / e.total * 100}%` }))); };
    xhr.onload = () => {
      if (xhr.status === 200) location.hash = '#/p/' + JSON.parse(xhr.responseText).id;
      else { toast('Upload failed'); route(); }
    };
    xhr.onerror = () => { toast('Upload failed'); route(); };
    xhr.send(fd);
  }
  file.addEventListener('change', () => upload(file.files[0]));
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); upload(e.dataTransfer.files[0]); });

  const body = h('div');
  const tabs = h('div', { class: 'tabs' });
  function drawTab() {
    tabs.replaceChildren(
      h('button', { class: tab === 'link' ? 'on' : '', onclick: () => { tab = 'link'; drawTab(); } }, 'Paste a link'),
      h('button', { class: tab === 'upload' ? 'on' : '', onclick: () => { tab = 'upload'; drawTab(); } }, 'Upload a video'));
    body.replaceChildren(tab === 'link' ? h('div', { class: 'row' }, url, go) : drop);
  }
  drawTab();
  const list = h('div', { class: 'plist' });
  $app.replaceChildren(
    h('div', { class: 'hero' }, h('h1', {}, 'Turn any video into shorts'),
      h('p', {}, 'Paste a link or upload a file. The best moments are found, cropped to 9:16, subtitled and ready to download.')),
    h('div', { class: 'card create' }, h('div', { style: 'text-align:center' }, tabs), body, file,
      h('div', { class: 'opts' },
        h('div', {}, h('label', {}, 'Short length'), sel('len', [['15-30', '15-30 seconds'], ['30-60', '30-60 seconds'], ['60-90', '60-90 seconds']])),
        h('div', {}, h('label', {}, 'How many'), sel('count', [['0', 'Auto'], ['3', '3'], ['5', '5'], ['8', '8'], ['12', '12']])),
        h('div', {}, h('label', {}, 'Framing'), sel('framing', [['crop', 'Center crop'], ['blur', 'Blurred background'], ['fit', 'Fit with black bars']])),
        h('div', {}, h('label', {}, 'Subtitles'), sel('subtitles', [['true', 'On'], ['off', 'Off']])))),
    h('h2', {}, 'Your projects'), list);
  every(2500, async () => {
    const items = await api('/projects');
    list.replaceChildren(...(items.length ? items.map(it => {
      const busy = !['ready', 'error'].includes(it.status);
      return h('a', { class: 'card pitem', href: '#/p/' + it.id },
        it.thumb ? h('img', { src: `/media/${it.id}/clips/${it.thumb}.jpg`, onerror: e => { e.target.style.visibility = 'hidden'; } }) : h('div', { class: 'ph' }),
        h('div', { class: 'grow' }, h('div', { class: 't' }, it.title),
          h('div', { class: 'muted small' }, busy ? `${STAGES[it.status] || it.message} ${it.progress ? Math.round(it.progress * 100) + '%' : ''}`
            : it.status === 'error' ? 'Failed: ' + it.message : `${it.clips} shorts - ${fmt(it.duration)} source`),
          busy ? h('div', { class: 'bar', style: 'margin-top:6px' }, h('i', { style: `width:${it.progress * 100}%` })) : null),
        h('span', { class: 'pill ' + (it.status === 'ready' ? 'ok' : it.status === 'error' ? 'err' : 'warn') }, it.status));
    }) : [h('div', { class: 'muted' }, 'Nothing yet. Create your first shorts above.')]));
  });
}

// ---------------------------------------------------------------- project
async function projectView(pid) {
  let p = await api('/projects/' + pid);
  crumbs([p.title]);
  const root = h('div');
  $app.replaceChildren(root);
  let sig = '';
  async function act(fn, done) { try { await fn(); if (done) toast(done); await refresh(true); } catch (e) { toast(e.message); } }
  function card(c, n) {
    const r = c.render, ready = r.status === 'done';
    const busy = r.status === 'queued' || r.status === 'rendering';
    const media = h('div', { class: 'media' });
    if (ready) media.append(h('video', { controls: true, preload: 'none', playsInline: true,
      poster: `/media/${pid}/clips/${c.id}.jpg?v=${r.version}`, src: `/media/${pid}/${r.file}?v=${r.version}` }));
    else media.append(h('div', { class: 'wait' }, busy ? h('div', { class: 'spinner' }) : null,
      h('div', {}, r.status === 'error' ? 'Render failed: ' + r.error : busy ? (r.status === 'queued' ? 'Waiting to render' : `Rendering ${Math.round(r.progress * 100)}%`) : 'Not rendered yet')));
    return h('div', { class: 'card clip' }, media,
      h('div', { class: 'body' },
        h('div', { class: 'title' }, `${n}. ${c.title}`),
        h('div', { class: 'muted small' }, `${fmt(c.start)} - ${fmt(c.end)} · ${Math.round((c.end - c.start) / c.speed)}s`,
          ready && r.stale ? h('span', { class: 'pill warn', style: 'margin-left:6px' }, 'edited') : null,
          ready && busy ? h('span', { class: 'pill warn', style: 'margin-left:6px' }, 're-rendering') : null),
        c.reason ? h('div', { class: 'muted small' }, c.reason) : null,
        h('div', { class: 'acts' },
          h('a', { class: 'btn sm', href: `#/p/${pid}/c/${c.id}` }, 'Edit'),
          ready ? h('a', { class: 'btn sm primary', href: `/api/projects/${pid}/clips/${c.id}/download` }, 'Download')
            : h('button', { class: 'sm', disabled: busy, onclick: () => act(() => api(`/projects/${pid}/clips/${c.id}/render`, { method: 'POST' })) }, 'Render'),
          h('button', { class: 'sm danger', title: 'Delete this short', style: 'flex:0',
            onclick: () => confirm('Delete this short?') && act(() => api(`/projects/${pid}/clips/${c.id}`, { method: 'DELETE' })) }, '✕'))));
  }
  function draw() {
    if (!['ready', 'error'].includes(p.status)) {
      root.replaceChildren(h('div', { class: 'card stage' }, h('div', { class: 'spinner' }),
        h('h2', { style: 'margin:0 0 6px' }, STAGES[p.status] || 'Working'), h('p', { class: 'muted' }, p.message),
        h('div', { class: 'bar' }, h('i', { style: `width:${p.progress * 100}%` })),
        h('p', { class: 'muted small' }, 'You can leave this page; processing continues in the background.')));
      return;
    }
    if (p.status === 'error') {
      root.replaceChildren(h('div', { class: 'card stage' }, h('h2', { style: 'margin-top:0' }, 'This video could not be processed'),
        h('p', { class: 'muted' }, p.message),
        h('button', { class: 'danger', onclick: async () => { await api('/projects/' + pid, { method: 'DELETE' }); location.hash = '#/'; } }, 'Delete project')));
      return;
    }
    const done = p.clips.filter(c => c.render.status === 'done').length;
    const stale = p.clips.some(c => c.render.stale && !['queued', 'rendering'].includes(c.render.status));
    root.replaceChildren(
      h('div', { class: 'spread', style: 'margin-bottom:16px' },
        h('div', {}, h('h1', { style: 'font-size:21px' }, p.title),
          h('div', { class: 'muted' }, `${p.clips.length} shorts · ${done} rendered · source ${fmt(p.duration)} · ${p.width}×${p.height}`)),
        h('div', { class: 'row wrap' },
          h('a', { class: 'btn primary', href: `/api/projects/${pid}/download`, onclick: e => { if (!done) { e.preventDefault(); toast('Nothing rendered yet'); } } }, 'Download all (.zip)'),
          stale ? h('button', { onclick: () => act(() => api(`/projects/${pid}/render`, { method: 'POST', json: { only_stale: true } })) }, 'Render changes') : null,
          h('button', { onclick: async () => {
            try {
              const last = p.clips.reduce((m, c) => Math.max(m, c.end), 0);
              const st = last + 45 <= p.duration ? last : 0;
              const c = await api(`/projects/${pid}/clips`, { method: 'POST', json: { start: st, end: Math.min(p.duration, st + 45) } });
              location.hash = `#/p/${pid}/c/${c.id}`;
            } catch (e) { toast(e.message); }
          } }, '+ New short'),
          h('button', { title: 'Throw away these shorts and pick again', onclick: () => {
            const len = prompt('Pick the shorts again. Length range in seconds (min-max):', `${p.settings.min_len}-${p.settings.max_len}`);
            if (!len) return;
            const [a, b] = len.split('-').map(Number);
            if (!(a > 0 && b > a)) return toast('Use the form 30-60');
            const n = prompt('How many shorts? (0 = auto)', String(p.settings.max_clips || 0));
            if (n == null) return;
            act(() => api(`/projects/${pid}/repick`, { method: 'POST', json: { min_len: a, max_len: b, max_clips: Number(n) || 0 } }), 'Picked again');
          } }, 'Re-pick'),
          h('button', { class: 'danger', onclick: async () => {
            if (!confirm('Delete this project and all its shorts?')) return;
            await api('/projects/' + pid, { method: 'DELETE' }); location.hash = '#/';
          } }, 'Delete'))),
      p.clips.length ? h('div', { class: 'grid' }, p.clips.map((c, i) => card(c, i + 1)))
        : h('div', { class: 'card muted' }, 'No shorts yet. Use "+ New short" to cut one by hand.'));
  }
  async function refresh(force) {
    p = await api('/projects/' + pid);
    // redraw only when something visible changed, so playing videos are not interrupted
    const s = JSON.stringify([p.status, p.message, Math.round(p.progress * 100), p.clips.map(c => [c.id, c.title, c.start, c.end, c.render.status, Math.round(c.render.progress * 50), c.render.stale, c.render.version])]);
    if (s !== sig || force) { sig = s; draw(); crumbs([p.title]); }
  }
  draw();
  every(1500, () => refresh(false));
}

// ---------------------------------------------------------------- editor
async function editorView(pid, cid) {
  const p = await api('/projects/' + pid);
  let clip = p.clips.find(c => c.id === cid);
  if (!clip) throw new Error('That short no longer exists');
  crumbs([p.title, '#/p/' + pid], ['Edit: ' + clip.title]);
  const W = 540, H = 960;
  // libass sizes fonts by line height, CSS by em: per-font factor keeps the preview true to the render
  const FS = { 'Arial Black': 0.71, 'Impact': 0.82, 'Segoe UI': 0.75, 'Bahnschrift': 0.83, 'Verdana': 0.82, 'Comic Sans MS': 0.72, 'Georgia': 0.88 };
  const fs = px => px * (FS[clip.subtitles.font] || 0.75) / 19.2;
  const video = h('video', { src: `/media/${pid}/source.mp4`, preload: 'auto', playsInline: true, crossOrigin: 'anonymous' });
  const canvas = h('canvas', { width: W, height: H });
  const ctx = canvas.getContext('2d');
  const capEl = h('div', { class: 'ov' }), titleEl = h('div', { class: 'ov' });
  const preview = h('div', { class: 'preview', onclick: toggle }, canvas, titleEl, capEl);
  const playBtn = h('button', { class: 'primary', onclick: toggle }, '▶ Play');
  const timeEl = h('span', { class: 'time' });
  const statusEl = h('div', { class: 'small muted' });
  let saveTimer = null, capsDirty = false, saving = Promise.resolve(), alive = true;
  let view = { a: 0, b: p.duration }, wide = false;
  cleanup.push(() => { alive = false; video.pause(); video.removeAttribute('src'); video.load(); });

  function toggle() {
    if (video.paused) {
      if (video.currentTime < clip.start || video.currentTime >= clip.end - 0.05) video.currentTime = clip.start;
      video.play();
    } else video.pause();
  }
  video.addEventListener('play', () => { playBtn.textContent = '❚❚ Pause'; });
  video.addEventListener('pause', () => { playBtn.textContent = '▶ Play'; });
  video.addEventListener('loadedmetadata', () => { video.currentTime = clip.start; });
  function seek(t) { video.currentTime = Math.max(0, Math.min(p.duration, t)); }

  // --- preview drawing
  function words(cap) {
    const toks = cap.text.split(/\s+/).filter(Boolean);
    if (cap.words && cap.words.length === toks.length) return cap.words.map((w, i) => ({ s: w.s, e: w.e, w: toks[i] }));
    const total = toks.reduce((n, t) => n + t.length + 1, 0) || 1;
    let t0 = cap.start;
    return toks.map(t => { const d = (cap.end - cap.start) * (t.length + 1) / total; const o = { s: t0, e: t0 + d, w: t }; t0 += d; return o; });
  }
  let lastCapKey = '';
  function frame() {
    if (!alive) return;
    requestAnimationFrame(frame);
    const t = video.currentTime, vw = video.videoWidth, vh = video.videoHeight;
    if (!video.paused && t >= clip.end) { video.pause(); video.currentTime = clip.start; }
    video.playbackRate = clip.speed; video.volume = Math.min(1, clip.volume);
    if (vw) {
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
      const cover = Math.max(W / vw, H / vh), fit = Math.min(W / vw, H / vh);
      if (clip.framing === 'crop') {
        const s = cover * clip.zoom, dw = vw * s, dh = vh * s;
        ctx.drawImage(video, -(dw - W) * clip.pan_x, -(dh - H) * clip.pan_y, dw, dh);
      } else {
        if (clip.framing === 'blur') {
          ctx.filter = 'blur(16px) brightness(0.85)';
          ctx.drawImage(video, (W - vw * cover) / 2, (H - vh * cover) / 2, vw * cover, vh * cover);
          ctx.filter = 'none';
        }
        const s = clip.framing === 'blur' ? fit * clip.zoom : fit;
        ctx.drawImage(video, (W - vw * s) / 2, (H - vh * s) / 2, vw * s, vh * s);
      }
    }
    // overlays
    const sub = clip.subtitles, ttl = clip.title_overlay;
    const showTitle = ttl.enabled && ttl.text.trim() && (!ttl.duration || (t - clip.start) / clip.speed <= ttl.duration);
    const tcss = showTitle ? `top:${ttl.pos_y}%;font-family:"${sub.font}";font-size:${fs(ttl.size)}cqh;color:${ttl.color};-webkit-text-stroke-width:${12 / 19.2}cqh` : 'display:none';
    if (titleEl.dataset.css !== tcss + ttl.text) {
      titleEl.dataset.css = tcss + ttl.text;
      titleEl.style.cssText = tcss;
      titleEl.textContent = ttl.text;
    }
    const cap = sub.enabled ? clip.captions.find(c => t >= c.start && t < c.end) : null;
    const ws = cap ? words(cap) : [];
    let active = -1;
    ws.forEach((w, i) => { if (t >= w.s) active = i; });
    const key = cap ? [cap.start, cap.text, active, JSON.stringify(sub)].join('|') : '';
    if (key !== lastCapKey) {
      lastCapKey = key;
      capEl.style.display = cap ? '' : 'none';
      if (cap) {
        capEl.style.cssText = `top:${sub.pos_y}%;font-family:"${sub.font}";font-size:${fs(sub.size)}cqh;color:${sub.color};-webkit-text-stroke-width:${sub.outline * 2 / 19.2}cqh;text-transform:${sub.uppercase ? 'uppercase' : 'none'}`;
        capEl.replaceChildren(...ws.flatMap((w, i) => [h('span', { style: sub.highlight_on && i === active ? `color:${sub.highlight}` : '' }, w.w), ' ']));
      }
      document.querySelectorAll('.cap').forEach(el => el.classList.toggle('now', !!cap && Number(el.dataset.start) === cap.start));
    }
    timeEl.textContent = `${fmt(Math.max(0, t - clip.start), 1)} / ${fmt(clip.end - clip.start, 1)}`;
    drawPlayhead(t);
  }

  // --- saving
  function changed(captionsToo) {
    if (captionsToo) capsDirty = true;
    statusEl.textContent = 'Saving...';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 450);
  }
  function save() {
    clearTimeout(saveTimer); saveTimer = null;
    const patch = { title: clip.title, start: clip.start, end: clip.end, framing: clip.framing, pan_x: clip.pan_x, pan_y: clip.pan_y,
      zoom: clip.zoom, speed: clip.speed, volume: clip.volume, subtitles: clip.subtitles, title_overlay: clip.title_overlay };
    if (capsDirty) { patch.captions = clip.captions; capsDirty = false; }
    saving = saving.then(() => api(`/projects/${pid}/clips/${cid}`, { method: 'PUT', json: patch })).then(c => {
      if (!alive) return;
      clip.render = c.render; clip.captions_edited = c.captions_edited;
      if (!saveTimer && !capsDirty && JSON.stringify(c.captions) !== JSON.stringify(clip.captions)) { clip.captions = c.captions; drawCaps(); }
      drawStatus();
    }).catch(e => toast(e.message));
    return saving;
  }
  cleanup.push(() => { if (saveTimer) save(); });
  function drawStatus() {
    const r = clip.render;
    statusEl.textContent = r.status === 'rendering' ? `Rendering ${Math.round(r.progress * 100)}%` : r.status === 'queued' ? 'Waiting to render'
      : r.status === 'error' ? 'Render failed: ' + r.error : r.status === 'done' ? (r.stale ? 'Saved. Edits not rendered yet.' : 'Rendered and up to date.') : 'Saved. Not rendered yet.';
    dl.style.display = r.status === 'done' ? '' : 'none';
    renderBtn.disabled = r.status === 'queued' || r.status === 'rendering';
  }
  const renderBtn = h('button', { class: 'primary', onclick: async () => {
    await save();
    try { clip.render = (await api(`/projects/${pid}/clips/${cid}/render`, { method: 'POST' })).render; drawStatus(); } catch (e) { toast(e.message); }
  } }, 'Render short');
  const dl = h('a', { class: 'btn', href: `/api/projects/${pid}/clips/${cid}/download` }, 'Download');
  every(1200, async () => {
    if (!['queued', 'rendering'].includes(clip.render.status)) return;
    const fresh = (await api('/projects/' + pid)).clips.find(c => c.id === cid);
    if (fresh) { clip.render = fresh.render; drawStatus(); if (fresh.render.status === 'done') toast('Short rendered'); }
  });

  // --- generic bound controls
  const getp = path => path.split('.').reduce((o, k) => o[k], clip);
  const setp = (path, v) => { const ks = path.split('.'); const last = ks.pop(); ks.reduce((o, k) => o[k], clip)[last] = v; };
  function field(label, path, type, o = {}) {
    const val = h('span', { class: 'val' });
    const show = () => { if (type === 'range') val.textContent = (o.fmt || (v => v))(getp(path)); };
    let input;
    const on = e => {
      const t = e.target;
      setp(path, type === 'checkbox' ? t.checked : (type === 'range' || type === 'number') ? Number(t.value) : t.value);
      show(); lastCapKey = ''; changed(); if (o.after) o.after();
    };
    if (type === 'select') input = h('select', { onchange: on }, o.options.map(([v, l]) => h('option', { value: v, selected: getp(path) === v }, l)));
    else if (type === 'checkbox') {
      input = h('input', { type, checked: getp(path), onchange: on });
      return h('label', { class: 'check field' + (o.wide ? ' wide' : '') }, input, label);
    } else input = h('input', { type, min: o.min, max: o.max, step: o.step, value: getp(path), oninput: on });
    show();
    return h('div', { class: 'field' + (o.wide ? ' wide' : '') }, h('label', {}, label, val), input);
  }

  // --- timeline
  const tl = h('div', { class: 'tl' });
  const selEl = h('div', { class: 'sel' }), hdA = h('div', { class: 'hd' }), hdB = h('div', { class: 'hd' }), ph = h('div', { class: 'ph' });
  const ticks = h('div');
  tl.append(ticks, selEl, hdA, hdB, ph);
  const rangeLabel = h('div', { class: 'spread small muted' });
  const pct = t => (t - view.a) / (view.b - view.a) * 100;
  function setView() {
    const len = clip.end - clip.start, pad = Math.max(12, len * 0.6);
    view = wide ? { a: 0, b: p.duration } : { a: Math.max(0, clip.start - pad), b: Math.min(p.duration, clip.end + pad) };
    const span = view.b - view.a, step = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200].find(s => span / s <= 10) || 1800;
    ticks.replaceChildren();
    for (let t = Math.ceil(view.a / step) * step; t < view.b; t += step) ticks.append(h('div', { class: 'tick', style: `left:${pct(t)}%` }, fmt(t)));
    drawTl();
  }
  function drawTl() {
    selEl.style.left = pct(clip.start) + '%'; selEl.style.width = (pct(clip.end) - pct(clip.start)) + '%';
    hdA.style.left = pct(clip.start) + '%'; hdB.style.left = pct(clip.end) + '%';
    rangeLabel.replaceChildren(h('span', {}, `Start ${fmt(clip.start, 1)}`), h('span', {}, `Length ${(clip.end - clip.start).toFixed(1)}s` + (clip.speed !== 1 ? ` (${((clip.end - clip.start) / clip.speed).toFixed(1)}s at ${clip.speed}×)` : '')), h('span', {}, `End ${fmt(clip.end, 1)}`));
  }
  function drawPlayhead(t) { const x = pct(t); ph.style.left = x + '%'; ph.style.display = x < 0 || x > 100 ? 'none' : ''; }
  const tAt = e => { const r = tl.getBoundingClientRect(); return view.a + Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (view.b - view.a); };
  function setRange(a, b) {
    clip.start = Math.round(Math.max(0, Math.min(a, b - 0.5)) * 100) / 100;
    clip.end = Math.round(Math.min(p.duration, Math.max(b, clip.start + 0.5)) * 100) / 100;
    drawTl(); changed();
  }
  function drag(handle, which) {
    handle.addEventListener('pointerdown', e => {
      e.stopPropagation(); handle.setPointerCapture(e.pointerId); video.pause();
      const move = ev => { const t = tAt(ev); which === 'a' ? setRange(t, clip.end) : setRange(clip.start, t); seek(which === 'a' ? clip.start : clip.end - 0.05); };
      const up = () => { handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); setView(); if (which === 'b') seek(Math.max(clip.start, clip.end - 2)); };
      handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', up);
    });
  }
  drag(hdA, 'a'); drag(hdB, 'b');
  tl.addEventListener('pointerdown', e => seek(tAt(e)));

  // --- captions list
  const capsEl = h('div', { class: 'caps' });
  const capsNote = h('span', { class: 'small muted' });
  function drawCaps() {
    capsNote.textContent = clip.captions_edited ? 'Hand-edited' : 'Automatic';
    capsEl.replaceChildren(...(clip.captions.length ? clip.captions.map((c, i) => h('div', { class: 'cap', 'data-start': c.start },
      h('span', { class: 'ct', title: 'Jump here', onclick: () => seek(c.start + 0.01) }, fmt(c.start - clip.start, 1)),
      h('input', { type: 'text', value: c.text, oninput: e => { c.text = e.target.value; clip.captions_edited = true; capsNote.textContent = 'Hand-edited'; lastCapKey = ''; changed(true); } }),
      h('button', { class: 'sm danger', title: 'Remove this caption', onclick: () => { clip.captions.splice(i, 1); clip.captions_edited = true; drawCaps(); lastCapKey = ''; changed(true); } }, '✕')))
      : [h('div', { class: 'muted small' }, 'No speech found in this part of the video.')]));
  }
  async function resetCaps() {
    await save();
    const c = await api(`/projects/${pid}/clips/${cid}`, { method: 'PUT', json: { captions_edited: false } });
    clip.captions = c.captions; clip.captions_edited = false; clip.render = c.render; drawCaps(); drawStatus(); lastCapKey = '';
  }

  const pc = v => Math.round(v * 100) + '%';
  $app.replaceChildren(h('div', { class: 'editor' },
    h('div', { class: 'stagebox' }, preview,
      h('div', { class: 'transport' }, playBtn, timeEl, h('span', { class: 'grow' }),
        h('button', { class: 'sm', title: 'Back to the start of the short', onclick: () => seek(clip.start) }, '⏮')),
      h('div', { class: 'row wrap', style: 'margin-top:12px' }, renderBtn, dl, h('a', { class: 'btn', href: '#/p/' + pid }, 'Done')),
      h('div', { style: 'margin-top:8px' }, statusEl)),
    h('div', { class: 'panels' },
      h('div', { class: 'card' }, h('div', { class: 'spread' }, h('h3', {}, 'Trim'),
          h('button', { class: 'sm', onclick: e => { wide = !wide; e.target.textContent = wide ? 'Zoom to short' : 'Show whole video'; setView(); } }, 'Show whole video')),
        tl, rangeLabel,
        h('div', { class: 'row wrap', style: 'margin-top:10px' },
          h('button', { class: 'sm', onclick: () => { setRange(video.currentTime, clip.end); setView(); } }, 'Start at playhead'),
          h('button', { class: 'sm', onclick: () => { setRange(clip.start, video.currentTime); setView(); } }, 'End at playhead'),
          h('button', { class: 'sm', onclick: () => { setRange(clip.start - 1, clip.end); setView(); seek(clip.start); } }, '−1s start'),
          h('button', { class: 'sm', onclick: () => { setRange(clip.start + 1, clip.end); setView(); seek(clip.start); } }, '+1s start'),
          h('button', { class: 'sm', onclick: () => { setRange(clip.start, clip.end - 1); setView(); } }, '−1s end'),
          h('button', { class: 'sm', onclick: () => { setRange(clip.start, clip.end + 1); setView(); } }, '+1s end')),
        h('div', { class: 'fields', style: 'margin-top:14px' },
          field('Title (used for the file name)', 'title', 'text', { wide: true }),
          field('Speed', 'speed', 'range', { min: 0.5, max: 2, step: 0.05, fmt: v => v + '×', after: drawTl }),
          field('Volume', 'volume', 'range', { min: 0, max: 2, step: 0.05, fmt: pc }))),
      h('div', { class: 'card' }, h('h3', {}, 'Framing'),
        h('div', { class: 'fields' },
          field('Mode', 'framing', 'select', { options: [['crop', 'Crop to fill'], ['blur', 'Blurred background'], ['fit', 'Fit with black bars']] }),
          field('Zoom', 'zoom', 'range', { min: 1, max: 3, step: 0.02, fmt: v => v.toFixed(2) + '×' }),
          field('Move left / right', 'pan_x', 'range', { min: 0, max: 1, step: 0.01, fmt: pc }),
          field('Move up / down', 'pan_y', 'range', { min: 0, max: 1, step: 0.01, fmt: pc }))),
      h('div', { class: 'card' }, h('h3', {}, 'Subtitles'),
        h('div', { class: 'fields' },
          field('Show subtitles', 'subtitles.enabled', 'checkbox'),
          field('Highlight the spoken word', 'subtitles.highlight_on', 'checkbox'),
          field('UPPERCASE', 'subtitles.uppercase', 'checkbox'),
          field('Font', 'subtitles.font', 'select', { options: META.fonts.map(f => [f, f]) }),
          field('Size', 'subtitles.size', 'range', { min: 40, max: 160, step: 2 }),
          field('Outline', 'subtitles.outline', 'range', { min: 0, max: 14, step: 1 }),
          field('Height on screen', 'subtitles.pos_y', 'range', { min: 8, max: 92, step: 1, fmt: v => v + '%' }),
          field('Words per caption', 'subtitles.words_per', 'range', { min: 1, max: 8, step: 1 }),
          field('Text colour', 'subtitles.color', 'color'),
          field('Highlight colour', 'subtitles.highlight', 'color')),
        h('div', { class: 'spread', style: 'margin:16px 0 8px' }, h('div', {}, h('b', {}, 'Caption text '), capsNote),
          h('button', { class: 'sm', title: 'Throw away text edits and rebuild from the transcript', onclick: resetCaps }, 'Reset to automatic')),
        capsEl),
      h('div', { class: 'card' }, h('h3', {}, 'Title text'),
        h('div', { class: 'fields' },
          field('Show a title on the video', 'title_overlay.enabled', 'checkbox', { wide: true }),
          field('Text', 'title_overlay.text', 'text', { wide: true }),
          field('Size', 'title_overlay.size', 'range', { min: 30, max: 140, step: 2 }),
          field('Height on screen', 'title_overlay.pos_y', 'range', { min: 5, max: 95, step: 1, fmt: v => v + '%' }),
          field('Seconds shown (0 = whole short)', 'title_overlay.duration', 'number', { min: 0, step: 0.5 }),
          field('Colour', 'title_overlay.color', 'color'))))));
  setView(); drawCaps(); drawStatus();
  requestAnimationFrame(frame);
}

api('/meta').then(m => { META = m; }).catch(() => {}).finally(route);
