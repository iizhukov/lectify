let currentWorkflow = null;
let nodesOnCanvas = [];
let selectedNode = null;
let nodeCounter = 0;

export function initGraphEditor(workflow) {
  currentWorkflow = workflow;
  nodesOnCanvas = [];
  selectedNode = null;
  nodeCounter = 0;

  const canvas = document.getElementById('workflow-canvas');
  const palette = document.getElementById('node-palette');

  if (!canvas || !palette) return;

  // Initialize SVG markers
  initEdgeMarkers();

  // Load existing nodes
  if (workflow && workflow.graph && workflow.graph.nodes) {
    workflow.graph.nodes.forEach(node => {
      createNodeElement(node.id, node.position_x, node.position_y, node);
    });
  }

  // Setup drag and drop
  palette.querySelectorAll('.palette-node').forEach(node => {
    node.addEventListener('dragstart', handleDragStart);
  });

  canvas.addEventListener('dragover', (e) => e.preventDefault());
  canvas.addEventListener('drop', handleDrop);

  // Setup node selection
  document.getElementById('nodes-container').addEventListener('click', handleNodeClick);

  // Setup edge drawing
  canvas.addEventListener('mousedown', startEdgeDrawing);
}

function initEdgeMarkers() {
  const svg = document.getElementById('edges-svg');
  if (!svg.querySelector('defs')) {
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
        <path d="M0,0 L0,6 L9,3 z" fill="#4B5563"/>
      </marker>
    `;
    svg.appendChild(defs);
  }
}

function handleDragStart(e) {
  e.dataTransfer.setData('template-id', e.target.dataset.templateId);
  e.dataTransfer.setData('node-name', e.target.dataset.nodeName);
}

function handleDrop(e) {
  e.preventDefault();
  const templateId = e.dataTransfer.getData('template-id');
  const nodeName = e.dataTransfer.getData('node-name');
  const rect = e.currentTarget.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;

  createNodeElement(templateId, x, y, { template_id: templateId, name: nodeName });
}

function createNodeElement(id, x, y, nodeData = {}) {
  const container = document.getElementById('nodes-container');
  if (!container) return;

  const nodeId = 'node_' + (++nodeCounter);

  const nodeEl = document.createElement('div');
  nodeEl.className = 'node-card absolute w-48 bg-gray-800 rounded-lg p-3 cursor-move border border-gray-700 hover:border-blue-500 transition-colors';
  nodeEl.dataset.nodeId = nodeId;
  nodeEl.style.left = x + 'px';
  nodeEl.style.top = y + 'px';

  nodeEl.innerHTML = `
    <div class="font-medium text-sm">${nodeData.name || id}</div>
    <div class="text-xs text-gray-400 mt-1">${nodeData.description || 'Node'}</div>
    <div class="flex items-center justify-between mt-2">
      <div class="w-3 h-3 rounded-full bg-green-500" title="Input"></div>
      <div class="w-3 h-3 rounded-full bg-blue-500" title="Output"></div>
    </div>
  `;

  makeDraggable(nodeEl);
  container.appendChild(nodeEl);

  nodesOnCanvas.push({
    id: nodeId,
    ...nodeData,
    position_x: x,
    position_y: y,
    element: nodeEl
  });

  return nodeId;
}

function makeDraggable(el) {
  let isDragging = false;
  let startX, startY, initialX, initialY;

  el.addEventListener('mousedown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    initialX = el.offsetLeft;
    initialY = el.offsetTop;

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  });

  function onMouseMove(e) {
    if (!isDragging) return;

    const dx = e.clientX - startX;
    const dy = e.clientY - startY;

    el.style.left = (initialX + dx) + 'px';
    el.style.top = (initialY + dy) + 'px';

    updateNodePosition(el.dataset.nodeId, initialX + dx, initialY + dy);
  }

  function onMouseUp() {
    isDragging = false;
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
  }
}

function updateNodePosition(nodeId, x, y) {
  const node = nodesOnCanvas.find(n => n.id === nodeId);
  if (node) {
    node.position_x = x;
    node.position_y = y;
  }
}

function handleNodeClick(e) {
  const nodeEl = e.target.closest('.node-card');
  if (!nodeEl) return;

  selectNode(nodeEl.dataset.nodeId);
}

function selectNode(nodeId) {
  nodesOnCanvas.forEach(n => {
    n.element.classList.remove('border-blue-500');
    n.element.classList.add('border-gray-700');
  });

  const node = nodesOnCanvas.find(n => n.id === nodeId);
  if (node) {
    node.element.classList.remove('border-gray-700');
    node.element.classList.add('border-blue-500');
    selectedNode = node;
    showNodeProperties(node);
  }
}

function showNodeProperties(node) {
  const panel = document.getElementById('node-properties');
  if (!panel) return;

  panel.innerHTML = `
    <div class="space-y-4">
      <div>
        <label class="block text-sm font-medium mb-2">Node ID</label>
        <input type="text" value="${node.id}" class="input-field text-sm" disabled>
      </div>
      <div>
        <label class="block text-sm font-medium mb-2">Name</label>
        <input type="text" value="${node.name || ''}" class="input-field text-sm"
               onchange="updateNodeName('${node.id}', this.value)">
      </div>
      <div>
        <label class="block text-sm font-medium mb-2">Input Mapping</label>
        <div class="space-y-2">
          ${(node.input_mapping || []).map((mapping, i) => `
            <div class="flex gap-2 items-center">
              <input type="text" value="${mapping.target_field}" class="input-field text-sm flex-1"
                     placeholder="target_field">
              <select class="input-field text-sm flex-1">
                <option value="$root.file_path" ${mapping.source === '$root.file_path' ? 'selected' : ''}>$root.file_path</option>
                <option value="$node.prev.output.path" ${mapping.source === '$node.prev.output.path' ? 'selected' : ''}>$node.prev.output.path</option>
              </select>
              <select class="input-field text-sm w-24">
                <option value="passthrough" ${mapping.transform === 'passthrough' ? 'selected' : ''}>passthrough</option>
                <option value="string" ${mapping.transform === 'string' ? 'selected' : ''}>string</option>
              </select>
            </div>
          `).join('')}
          <button onclick="addInputMapping('${node.id}')" class="text-sm text-blue-400 hover:text-blue-300">
            + Add Mapping
          </button>
        </div>
      </div>
      <button onclick="deleteNode('${node.id}')" class="w-full text-red-400 hover:text-red-300 text-sm py-2">
        Delete Node
      </button>
    </div>
  `;
}

window.updateNodeName = function(nodeId, name) {
  const node = nodesOnCanvas.find(n => n.id === nodeId);
  if (node) {
    node.name = name;
    node.element.querySelector('.font-medium').textContent = name;
  }
};

window.addInputMapping = function(nodeId) {
  const node = nodesOnCanvas.find(n => n.id === nodeId);
  if (node) {
    node.input_mapping = node.input_mapping || [];
    node.input_mapping.push({ target_field: '', source: '$root.file_path', transform: 'passthrough' });
    showNodeProperties(node);
  }
};

window.deleteNode = function(nodeId) {
  const node = nodesOnCanvas.find(n => n.id === nodeId);
  if (node) {
    node.element.remove();
    nodesOnCanvas = nodesOnCanvas.filter(n => n.id !== nodeId);
    document.getElementById('node-properties').innerHTML = '<p class="text-gray-400 text-sm">Select a node to edit</p>';
  }
};

function startEdgeDrawing(e) {
  const canvas = document.getElementById('workflow-canvas');
  if (e.target !== canvas && !e.target.closest('#workflow-canvas')) return;

  const startX = e.clientX;
  const startY = e.clientY;

  const svg = document.getElementById('edges-svg');
  const tempLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  tempLine.setAttribute('stroke', '#3B82F6');
  tempLine.setAttribute('stroke-width', '2');
  tempLine.setAttribute('fill', 'none');
  tempLine.setAttribute('stroke-dasharray', '5,5');
  svg.appendChild(tempLine);

  function onMove(e) {
    const currentX = e.clientX;
    const currentY = e.clientY;
    tempLine.setAttribute('d', `M ${startX},${startY} C ${startX},${currentY} ${currentX},${startY} ${currentX},${currentY}`);
  }

  function onUp() {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    tempLine.remove();
  }

  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

export function saveGraph() {
  const nodes = nodesOnCanvas.map(n => ({
    id: n.id,
    template_id: n.template_id,
    name: n.name,
    position_x: n.position_x,
    position_y: n.position_y,
    input_mapping: n.input_mapping || []
  }));

  return {
    nodes,
    edges: []
  };
}