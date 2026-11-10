/* Standalone viewer: no network requests, editor callbacks or external runtime. */
const panels = [...document.querySelectorAll('[role="tabpanel"]')];
const state = new Map();
const markerColors = {incoming: '#58a6ff', outgoing: '#ffb454', both: '#d2a8ff'};

for (const panel of panels) {
  const canvas = panel.querySelector('.canvas');
  const svg = canvas.querySelector('svg');
  const nodes = [...svg.querySelectorAll('[data-node-id]')];
  const edges = [...svg.querySelectorAll('[data-source][data-target]')];
  const data = {pinned: null, hovered: null, focused: null, zoom: 1, nodes, edges, canvas};
  state.set(panel, data);

  // Each highlighted edge gets its own color-specific marker. Shared markers
  // are never recolored, so unrelated arrowheads keep their original color.
  for (const edge of edges) {
    edge.originalMarkers = {};
    for (const attribute of ['marker-end', 'marker-start']) {
      const original = edge.getAttribute(attribute);
      edge.originalMarkers[attribute] = original;
      const id = original?.match(/#([^)]*)\)/)?.[1];
      const marker = id && svg.querySelector(`[id="${CSS.escape(id)}"]`);
      if (!marker) continue;
      for (const [direction, color] of Object.entries(markerColors)) {
        const cloneId = `${id}-${direction}`;
        if (!svg.querySelector(`[id="${CSS.escape(cloneId)}"]`)) {
          const clone = marker.cloneNode(true);
          clone.id = cloneId;
          for (const path of clone.querySelectorAll('path, polygon, circle')) {
            path.style.setProperty('fill', color, 'important');
            path.style.setProperty('stroke', color, 'important');
          }
          marker.parentNode.append(clone);
        }
      }
    }
  }

  function paint() {
    const selected = data.hovered ?? data.focused ?? data.pinned;
    canvas.classList.toggle('has-selection', selected !== null);
    for (const node of nodes) {
      node.classList.toggle('is-selected', node.dataset.nodeId === selected);
      node.setAttribute('aria-pressed', String(node.dataset.nodeId === data.pinned));
    }
    const connections = [];
    for (const edge of edges) {
      const incoming = selected !== null && edge.dataset.target === selected;
      const outgoing = selected !== null && edge.dataset.source === selected;
      const direction = incoming && outgoing ? 'both' : incoming ? 'incoming' : outgoing ? 'outgoing' : null;
      for (const candidate of Object.keys(markerColors)) edge.classList.toggle(`is-${candidate}`, direction === candidate);
      for (const [attribute, original] of Object.entries(edge.originalMarkers)) {
        if (original === null) continue;
        edge.setAttribute(attribute, direction ? original.replace(/#([^)]*)\)/, `#$1-${direction})`) : original);
      }
      if (direction) connections.push({edge, direction});
    }
    const selectedNode = nodes.find(node => node.dataset.nodeId === selected);
    panel.querySelector('.selection-title').textContent = selectedNode?.dataset.label ?? 'No node selected';
    panel.querySelector('.status').textContent = selected === null
      ? 'Hover a node to trace its immediate connections. Click to keep the selection.'
      : `${connections.filter(c => c.direction !== 'outgoing').length} incoming · ${connections.filter(c => c.direction !== 'incoming').length} outgoing · ${data.pinned === selected ? 'Pinned — click again or press Escape to release' : 'Preview — click to pin'}`;
    const list = panel.querySelector('.connections');
    list.replaceChildren();
    for (const {edge, direction} of connections) {
      const other = direction === 'incoming' ? edge.dataset.source : edge.dataset.target;
      const node = nodes.find(item => item.dataset.nodeId === other);
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.direction = direction;
      button.textContent = `${direction === 'incoming' ? 'From' : 'To'}: ${node?.dataset.label ?? other}`;
      button.addEventListener('click', () => { data.hovered = null; data.focused = null; data.pinned = other; paint(); });
      list.append(button);
    }
  }

  function clear() { data.pinned = null; data.hovered = null; data.focused = null; paint(); }
  data.clear = clear;
  for (const node of nodes) {
    const id = node.dataset.nodeId;
    node.setAttribute('tabindex', '0');
    node.setAttribute('role', 'button');
    node.setAttribute('aria-label', `${node.dataset.label}. Highlight connections; press Enter to pin.`);
    node.addEventListener('pointerenter', () => { data.hovered = id; paint(); });
    node.addEventListener('pointerleave', () => { data.hovered = null; paint(); });
    node.addEventListener('focus', () => { data.focused = id; paint(); });
    node.addEventListener('blur', () => { data.focused = null; paint(); });
    function toggle() { data.pinned = data.pinned === id ? null : id; paint(); }
    node.addEventListener('click', event => { event.stopPropagation(); toggle(); });
    node.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); }
    });
  }
  svg.addEventListener('click', event => { if (!event.target.closest('[data-node-id]')) clear(); });
  panel.querySelector('[data-action=clear]').addEventListener('click', clear);
  for (const button of panel.querySelectorAll('[data-zoom]')) {
    button.addEventListener('click', () => {
      data.zoom = button.dataset.zoom === 'fit' ? 1 : Math.max(.6, Math.min(3, data.zoom + Number(button.dataset.zoom)));
      svg.style.width = `${data.zoom * 100}%`;
    });
  }
  paint();
}

for (const tab of document.querySelectorAll('[role=tab]')) {
  tab.addEventListener('click', () => {
    for (const other of document.querySelectorAll('[role=tab]')) other.setAttribute('aria-selected', String(other === tab));
    for (const panel of panels) panel.hidden = panel.id !== tab.getAttribute('aria-controls');
  });
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') for (const data of state.values()) data.clear();
});
