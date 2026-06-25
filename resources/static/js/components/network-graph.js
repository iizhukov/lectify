const NODE_W = 180;
const NODE_H = 56;

const STATUS_COLORS = {
  completed: '#16a34a',
  running:   '#d97706',
  pending:   '#9ca3af',
  failed:    '#dc2626',
};

export function renderNetworkGraph(svgEl, nodes, edges, onNodeClick) {
  svgEl.innerHTML = '';
  if (!nodes || !nodes.length) return;

  let panX = 0, panY = 0, scale = 1;
  let isPanning = false;
  let lastX = 0, lastY = 0;

  // --- Layout ---
  // Build column depths via BFS from roots
  const inDeg = {};
  nodes.forEach(n => { inDeg[n.id] = 0; });
  (edges || []).forEach(e => { if (inDeg[e.to_node_id] !== undefined) inDeg[e.to_node_id]++; });

  const depth = {};
  const queue = nodes.filter(n => inDeg[n.id] === 0).map(n => n.id);
  queue.forEach(id => { depth[id] = 0; });
  const adj = {};
  (edges || []).forEach(e => {
    if (!adj[e.from_node_id]) adj[e.from_node_id] = [];
    adj[e.from_node_id].push(e.to_node_id);
  });
  let qi = 0;
  while (qi < queue.length) {
    const cur = queue[qi++];
    (adj[cur] || []).forEach(next => {
      if (depth[next] === undefined) {
        depth[next] = depth[cur] + 1;
        queue.push(next);
      }
    });
  }
  nodes.forEach(n => { if (depth[n.id] === undefined) depth[n.id] = 0; });

  // Group by column
  const cols = {};
  nodes.forEach(n => {
    const c = depth[n.id];
    if (!cols[c]) cols[c] = [];
    cols[c].push(n);
  });

  const colCount = Math.max(...Object.keys(cols).map(Number)) + 1;
  const colSpacing = Math.max(NODE_W + 60, (svgEl.clientWidth - 40) / colCount);
  const rowSpacing = NODE_H + 40;

  const pos = {};
  Object.entries(cols).forEach(([c, bucket]) => {
    const x = parseInt(c) * colSpacing + 20;
    bucket.forEach((n, ri) => {
      const totalH = bucket.length * (NODE_H + 40);
      const offsetY = (svgEl.clientHeight - totalH) / 2;
      const y = offsetY + ri * rowSpacing + 20;
      pos[n.id] = { x, y };
    });
  });

  // --- SVG setup ---
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

  // Arrow marker
  const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
  marker.setAttribute('id', 'arrow');
  marker.setAttribute('markerWidth', '8');
  marker.setAttribute('markerHeight', '6');
  marker.setAttribute('refX', '8');
  marker.setAttribute('refY', '3');
  marker.setAttribute('orient', 'auto');
  const arrowPoly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  arrowPoly.setAttribute('points', '0 0, 8 3, 0 6');
  arrowPoly.setAttribute('fill', '#AAAAAA');
  marker.appendChild(arrowPoly);
  defs.appendChild(marker);

  // Drop shadow
  const filter = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
  filter.setAttribute('id', 'shadow');
  filter.setAttribute('x', '-20%'); filter.setAttribute('y', '-20%');
  filter.setAttribute('width', '140%'); filter.setAttribute('height', '140%');
  const fds = document.createElementNS('http://www.w3.org/2000/svg', 'feDropShadow');
  fds.setAttribute('dx', '0'); fds.setAttribute('dy', '2');
  fds.setAttribute('stdDeviation', '3'); fds.setAttribute('flood-opacity', '0.08');
  filter.appendChild(fds);
  defs.appendChild(filter);
  svgEl.appendChild(defs);

  // Background dot grid (redrawn on pan/zoom via CSS)
  svgEl.style.cursor = 'grab';

  function updateBackground() {
    const dotSpacing = 20 * scale;
    const ox = ((panX % dotSpacing) + dotSpacing) % dotSpacing;
    const oy = ((panY % dotSpacing) + dotSpacing) % dotSpacing;
    svgEl.style.backgroundImage = 'radial-gradient(circle, #d1d5db 1px, transparent 1px)';
    svgEl.style.backgroundSize = `${dotSpacing}px ${dotSpacing}px`;
    svgEl.style.backgroundPosition = `${ox}px ${oy}px`;
  }

  // Viewport group (all content inside)
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('id', 'graph-viewport');
  svgEl.appendChild(g);

  function applyTransform() {
    g.setAttribute('transform', `translate(${panX},${panY}) scale(${scale})`);
    updateBackground();
  }
  applyTransform();

  // --- Draw edges ---
  (edges || []).forEach(edge => {
    const from = pos[edge.from_node_id];
    const to   = pos[edge.to_node_id];
    if (!from || !to) return;

    const sx = from.x + NODE_W;
    const sy = from.y + NODE_H / 2;
    const tx = to.x;
    const ty = to.y + NODE_H / 2;
    const cx1 = sx + (tx - sx) * 0.5;

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M ${sx} ${sy} C ${cx1} ${sy}, ${cx1} ${ty}, ${tx} ${ty}`);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#AAAAAA');
    path.setAttribute('stroke-width', '1.5');
    path.setAttribute('marker-end', 'url(#arrow)');
    g.appendChild(path);
  });

  // --- Draw nodes ---
  nodes.forEach(node => {
    const p = pos[node.id];
    if (!p) return;
    const color = STATUS_COLORS[node.status] || STATUS_COLORS.pending;
    const label = node.node_name || node.id || '';
    const statusLabel = node.status === 'running' && node.progress_percent != null
      ? `${node.progress_percent}%` : (node.status || '');

    const ng = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    ng.style.cursor = 'pointer';
    ng.addEventListener('click', () => onNodeClick && onNodeClick(node));

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', p.x); rect.setAttribute('y', p.y);
    rect.setAttribute('width', NODE_W); rect.setAttribute('height', NODE_H);
    rect.setAttribute('rx', '8');
    rect.setAttribute('fill', '#ffffff');
    rect.setAttribute('stroke', color);
    rect.setAttribute('stroke-width', '1.5');
    rect.setAttribute('filter', 'url(#shadow)');
    ng.appendChild(rect);

    // Status dot
    const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('cx', p.x + 14); dot.setAttribute('cy', p.y + 18);
    dot.setAttribute('r', '4'); dot.setAttribute('fill', color);
    ng.appendChild(dot);

    // Node name — wrap to 2 lines
    const maxCharsPerLine = Math.floor((NODE_W - 36) / 7.2);
    const words = label.split(' ');
    let line1 = '', line2 = '';
    for (const w of words) {
      if ((line1 + (line1 ? ' ' : '') + w).length <= maxCharsPerLine) {
        line1 += (line1 ? ' ' : '') + w;
      } else {
        line2 += (line2 ? ' ' : '') + w;
      }
    }
    if (line2.length > maxCharsPerLine) line2 = line2.slice(0, maxCharsPerLine - 1) + '…';

    const t1 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t1.setAttribute('x', p.x + 26); t1.setAttribute('y', p.y + (line2 ? 16 : 22));
    t1.setAttribute('font-size', '12'); t1.setAttribute('font-family', 'system-ui,sans-serif');
    t1.setAttribute('font-weight', '500'); t1.setAttribute('fill', '#222222');
    t1.textContent = line1;
    ng.appendChild(t1);

    if (line2) {
      const t2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t2.setAttribute('x', p.x + 26); t2.setAttribute('y', p.y + 29);
      t2.setAttribute('font-size', '11'); t2.setAttribute('font-family', 'system-ui,sans-serif');
      t2.setAttribute('fill', '#555555');
      t2.textContent = line2;
      ng.appendChild(t2);
    }

    // Status label bottom-left
    const st = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    st.setAttribute('x', p.x + 10); st.setAttribute('y', p.y + NODE_H - 8);
    st.setAttribute('font-size', '10'); st.setAttribute('font-family', 'system-ui,sans-serif');
    st.setAttribute('fill', color);
    st.textContent = statusLabel;
    ng.appendChild(st);

    g.appendChild(ng);
  });

  // --- Pan: LMB drag ---
  svgEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    // Don't pan if clicking a node
    if (e.target.closest('g[style*="cursor: pointer"], g[style*="cursor:pointer"]')) return;
    isPanning = true;
    lastX = e.clientX; lastY = e.clientY;
    svgEl.style.cursor = 'grabbing';
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!isPanning) return;
    panX += e.clientX - lastX;
    panY += e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    applyTransform();
  });

  window.addEventListener('mouseup', () => {
    if (!isPanning) return;
    isPanning = false;
    svgEl.style.cursor = 'grab';
  });

  // --- Zoom: scroll ---
  svgEl.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 0.9;
    const newScale = Math.min(Math.max(scale * factor, 0.1), 4);
    const rect = svgEl.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    panX = mx - (mx - panX) * (newScale / scale);
    panY = my - (my - panY) * (newScale / scale);
    scale = newScale;
    applyTransform();
  }, { passive: false });

  // Reset on double-click
  svgEl.addEventListener('dblclick', () => {
    panX = 0; panY = 0; scale = 1;
    applyTransform();
  });

  svgEl.addEventListener('contextmenu', e => e.preventDefault());
}
