/**
 * Plugin registry — all data loaded from backend.
 *
 * To add a new plugin: define it as a Python class in src/plugins/plugins/<name>/plugin.py
 * with id, name, description, color, icon_svg, parameters_schema — no frontend changes needed.
 */

import { api } from './api.js';

const _defaultIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 10h16M4 14h10"/></svg>`;

// Module-level state — populated by loadPlugins()
export let PLUGINS = [];
export let PLUGIN_MAP = {};
export let PLUGIN_COLORS = {};
export let PLUGIN_INPUTS = {};
export let PLUGIN_OUTPUTS = {};
export let PLUGIN_DEFAULTS = {};

/** Derive { type: 'input'|'select'|'bool', options?: [] } from a parameters_schema entry. */
function _paramTypeFromSchema(param) {
  if (param.type === 'bool') return { type: 'bool' };
  if (param.options && param.options.length > 0) return { type: 'select', options: param.options };
  return { type: 'input' };
}

/** Extract default values and param-type config from parameters_schema. */
function _extractDefaultsAndParamTypes(schema) {
  const defaults = {};
  const paramTypes = {};
  for (const p of schema) {
    if (p.default !== undefined && p.default !== null) defaults[p.name] = p.default;
    paramTypes[p.name] = _paramTypeFromSchema(p);
  }
  return { defaults, paramTypes };
}

function _buildDerived() {
  PLUGIN_MAP     = Object.fromEntries(PLUGINS.map(p => [p.id, p]));
  PLUGIN_COLORS  = Object.fromEntries(PLUGINS.map(p => [p.id, p.color]));
  PLUGIN_INPUTS  = Object.fromEntries(PLUGINS.map(p => [p.id, p.inputs]));
  PLUGIN_OUTPUTS = Object.fromEntries(PLUGINS.map(p => [p.id, p.outputs]));
  PLUGIN_DEFAULTS = Object.fromEntries(PLUGINS.map(p => [p.id, p.defaultParams]));
}

/** Load plugins from backend. Call once at page init. */
export async function loadPlugins() {
  const raw = await api.nodes.plugins();
  PLUGINS = raw.map(p => {
    const { defaults, paramTypes } = _extractDefaultsAndParamTypes(p.parameters_schema || []);
    return {
      id: p.id,
      name: p.name,
      description: p.description || '',
      color: p.color || '#9ca3af',
      icon: p.icon_svg || _defaultIcon,
      inputs: p.inputs || [],
      outputs: p.outputs || [],
      defaultParams: defaults,
      paramTypes,
      parametersSchema: p.parameters_schema || [],
    };
  });
  _buildDerived();
  return PLUGINS;
}

/** Returns param type config for a plugin+param key, e.g. { type: 'select', options: [...] }. */
export function getParamType(pluginId, key) {
  return PLUGIN_MAP[pluginId]?.paramTypes?.[key] ?? { type: 'input' };
}
