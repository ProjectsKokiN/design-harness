// VariablesとText/Effect/Color Stylesを全モードで書き出す。案件はCOLLECTION_SCOPEを指定する。
function val(n, key) {
  let v;
  try { v = n[key]; } catch (e) { return null; }
  if (typeof v === 'symbol') return 'MIXED';
  return v === undefined ? null : v;
}
const r2 = x => Math.round(x * 100) / 100;
const hex = c => {
  const to = x => Math.round(x * 255).toString(16).padStart(2, '0');
  return '#' + to(c.r) + to(c.g) + to(c.b) + (c.a != null && c.a < 1 ? to(c.a) : '');
};
const nameOfVar = async id => { const v = await figma.variables.getVariableByIdAsync(id); if (!v) throw new Error('別名参照を取得できません: ' + id); return v.name; };
const boundNames = async bv => {
  const o = {};
  for (const [k, b] of Object.entries(bv || {})) {
    if (Array.isArray(b)) continue;
    if (b && b.id) o[k] = await nameOfVar(b.id);
  }
  return o;
};

const out = { $meta: {
  source: 'Figma Plugin API（getLocalVariableCollectionsAsync / getLocalTextStylesAsync / getLocalEffectStylesAsync / getLocalPaintStylesAsync）',
  fileKey: figma.fileKey ?? null,
  note: 'この書き出しを design/gen/gen_tokens.py が読む。手で編集しない',
}, collections: {}, textStyles: [], effectStyles: [], colorStyles: [] };

// この案件の生成器が扱うコレクションだけを読む。Figmaの作業用コレクションは取り込まない。
const COLLECTION_SCOPE = []; // 空なら全コレクション。絞るときは案件が指定する。
out.$meta.collectionScope = COLLECTION_SCOPE;

for (const col of await figma.variables.getLocalVariableCollectionsAsync()) {
  if (COLLECTION_SCOPE.length && !COLLECTION_SCOPE.includes(col.name)) continue;
  const modes = col.modes.map(m => m.name);
  if (new Set(modes).size !== modes.length || out.collections[col.name]) throw new Error('コレクションまたはモード名が重複しています: ' + col.name);
  const rows = [];
  for (const id of col.variableIds) {
    const v = await figma.variables.getVariableByIdAsync(id);
    if (!v) throw new Error('変数を取得できません: ' + id);
    const row = { name: v.name, type: v.resolvedType, values: {} };
    for (const m of col.modes) {
      const raw = v.valuesByMode[m.modeId];
      if (raw === undefined) throw new Error('モードの値がありません: ' + v.name + '/' + m.name);
      if (raw && raw.type === 'VARIABLE_ALIAS') row.values[m.name] = { alias: await nameOfVar(raw.id) };
      else if (v.resolvedType === 'COLOR' && raw) row.values[m.name] = hex(raw);
      else row.values[m.name] = typeof raw === 'number' ? r2(raw) : raw;
    }
    row.scopes = v.scopes;
    // **key を書く**（候補6・2026-11-03）。作り直すと key が変わり、使う側のつながりが切れる
    if (v.key) row.key = v.key;
    // **id も書く**（#179・2026-11-03）。REST は変数を id でしか返さないので、名前に引く対応表になる
    row.id = v.id;
    if (v.description) row.description = v.description;
    rows.push(row);
  }
  out.collections[col.name] = { modes, variables: rows };
}

for (const s of await figma.getLocalTextStylesAsync()) {
  const lh = val(s, 'lineHeight'), ls = val(s, 'letterSpacing');
  out.textStyles.push({
    name: s.name,
    fontName: s.fontName,
    fontSize: s.fontSize,
    lineHeight: lh && lh !== 'MIXED' ? (lh.unit === 'AUTO' ? { unit: 'AUTO' } : { unit: lh.unit, value: r2(lh.value) }) : lh,
    letterSpacing: ls && ls !== 'MIXED' ? { unit: ls.unit, value: r2(ls.value) } : ls,
    paragraphSpacing: s.paragraphSpacing,
    textCase: s.textCase, textDecoration: s.textDecoration,
    bound: await boundNames(s.boundVariables),
  });
}

for (const s of await figma.getLocalEffectStylesAsync()) {
  const effects = [];
  for (const e of s.effects) {
    const o = { type: e.type, visible: e.visible !== false };
    if (e.radius != null) o.radius = e.radius;
    if (e.blurType) o.blurType = e.blurType;
    if (e.startRadius != null) o.startRadius = e.startRadius;
    if (e.startOffset) o.startOffset = e.startOffset;
    if (e.endOffset) o.endOffset = e.endOffset;
    if (e.color) o.color = hex(e.color);
    if (e.offset) o.offset = e.offset;
    if (e.spread != null) o.spread = e.spread;
    if (e.blendMode) o.blendMode = e.blendMode;
    if (e.type === 'NOISE') {
      o.noiseType = e.noiseType;
      o.noiseSize = e.noiseSize;
      if (e.noiseSizeVector) o.noiseSizeVector = e.noiseSizeVector;
      o.density = e.density;
      if (e.secondaryColor) o.secondaryColor = hex(e.secondaryColor);
    }
    o.bound = await boundNames(e.boundVariables);
    effects.push(o);
  }
  out.effectStyles.push({ name: s.name, effects });
}

for (const s of await figma.getLocalPaintStylesAsync()) {
  const paints = [];
  for (const p of s.paints) {
    const o = { type: p.type, visible: p.visible !== false, opacity: p.opacity };
    if (p.gradientStops) o.stops = [];
    for (const g of p.gradientStops || []) {
      const b = g.boundVariables && g.boundVariables.color;
      o.stops.push({ position: r2(g.position), color: hex(g.color), alias: b ? await nameOfVar(b.id) : null });
    }
    if (p.gradientTransform) o.gradientTransform = p.gradientTransform.map(r => r.map(r2));
    if (p.color) { o.color = hex(p.color); const b = p.boundVariables && p.boundVariables.color; if (b) o.alias = await nameOfVar(b.id); }
    paints.push(o);
  }
  out.colorStyles.push({ name: s.name, paints });
}

out.$meta.declared = {
  collections: Object.keys(out.collections).length,
  variables: Object.values(out.collections).reduce((n, c) => n + c.variables.length, 0),
  textStyles: out.textStyles.length,
  effectStyles: out.effectStyles.length,
  colorStyles: out.colorStyles.length,
};
// 中身のハッシュ（design/harness/tools/digest_check.py と同じ式）。
// 写した後に手で直していないか・写し間違いが無いかの証明になる
const canon = v => Array.isArray(v) ? '[' + v.map(canon).join(',') + ']'
  : (v && typeof v === 'object') ? '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}'
  : JSON.stringify(v);
const fnv = s => { let x = 0x811c9dc5; for (const ch of s) { x ^= ch.codePointAt(0) & 0xFF; x = (x + ((x << 1) + (x << 4) + (x << 7) + (x << 8) + (x << 24))) >>> 0; } return x >>> 0; };
const payload = Object.fromEntries(Object.entries(out).filter(([k]) => k !== '$meta'));
const body = canon(payload);
out.$meta.payloadDigest = { algo: 'FNV-1a 32bit', rows: Object.keys(payload).length, chars: [...body].length, value: fnv(body) };
// ONLY_META: 中身を写し終えたあと、$meta だけを取り直すとき true にする
if (typeof ONLY_META !== 'undefined' && ONLY_META) return JSON.stringify(out.$meta);
return JSON.stringify(out);
