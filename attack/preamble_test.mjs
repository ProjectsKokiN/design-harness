// 書き出し器のひな形が figma.mixed で落ちないかを実際に回して見る（#32・#10）。
//
// 実害（qnd-database・2026-09-03）: `strokeWeight` が figma.mixed（Symbol）を
// 返し、テンプレート文字列に入れた瞬間に書き出しが止まって
// **12部品のうち1件も取れなかった。**
//
// 走らせ方: node attack/preamble_test.mjs

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'exporters', '_preamble.js'), 'utf8');

// ひな形は `use_figma` に貼る前提で import できない。**そのまま評価する。**
const body = src.replace(/^const ALLOW_PAGES[^\n]*$/m, 'const ALLOW_PAGES = [];');
const load = new Function('figma', `${body}; return { val, num, revZ, h };`);

const MIXED = Symbol('figma.mixed');
const { val, num, revZ, h } = load({ mixed: MIXED, root: { children: [] } });

let ok = true;
const check = (cond, msg) => { if (!cond) { console.log(`NG: ${msg}`); ok = false; } };

// ── #32: mixed を文字列に入れても落ちない ────────────────────────────
const node = {
  strokeWeight: MIXED,          // 辺ごとに太さが違う
  cornerRadius: MIXED,
  opacity: 0.5,
  width: 12.345,
  name: 'Footer',
  get broken() { throw new Error('この getter は投げる'); },
};

check(val(node, 'strokeWeight') === 'MIXED', 'mixed を MIXED にしていない');
check(val(node, 'cornerRadius') === 'MIXED', 'cornerRadius の mixed を見ていない');
check(val(node, 'opacity') === 0.5, 'ふつうの値が変わった');
check(val(node, 'ない') === null, '無いキーが null でない');
check(val(node, 'broken') === null, '投げる getter で落ちた');
check(num(node, 'width') === 12.35, '数の丸めが違う');
check(num(node, 'strokeWeight') === 'MIXED', 'num が mixed を数に潰した');

// **文字列に入れて落ちないこと**が本題（実害そのものの形）
try {
  const line = `w=${num(node, 'width')}|sw=${val(node, 'strokeWeight')}`;
  check(line === 'w=12.35|sw=MIXED', `行の形が違う: ${line}`);
} catch (e) {
  check(false, `文字列にして落ちた: ${e.message}`);
}

// 素で書くと落ちることも見ておく（この道具が守っているものの確認）
let raw = null;
try { raw = `sw=${node.strokeWeight}`; } catch (e) { raw = 'THREW'; }
check(raw === 'THREW', '素の書き方が落ちない（この試験の前提が崩れている）');

// ── #10: 重なり順は生の真偽値のまま ──────────────────────────────
check(revZ({ itemReverseZIndex: true }) === true, 'true を返さない');
check(revZ({ itemReverseZIndex: false }) === false, 'false を返さない');
check(revZ({}) === null, '無いときに null を返さない');
check(revZ({ itemReverseZIndex: MIXED }) === null, 'mixed を真偽値にした');
// **意味に翻訳していないこと。** 'top' などに変えると、それが「正」になる
check(typeof revZ({ itemReverseZIndex: true }) === 'boolean',
      '重なり順を意味に翻訳している（生の値のままにする）');

// ── #26: インスタンスの寸法の上書きが行に出るか ──────────────────
{
  const frames = readFileSync(join(here, '..', 'exporters', 'export_frames.js'), 'utf8');
  const i = frames.indexOf("if (R(m.width) !== R(n.width)");
  check(i > 0, 'export_frames.js に寸法の上書きの判定が無い');
  // その場で同じ式を回して、行の形まで見る
  const R = (x) => (x == null ? null : Math.round(x * 100) / 100);
  const line = (m, n) =>
    (R(m.width) !== R(n.width) || R(m.height) !== R(n.height))
      ? 'override=' + R(m.width) + 'x' + R(m.height) + '->' + R(n.width) + 'x' + R(n.height)
      : null;
  check(line({ width: 48, height: 48 }, { width: 360, height: 360 })
        === 'override=48x48->360x360', '上書きの行の形が違う');
  check(line({ width: 48, height: 48 }, { width: 48, height: 48 }) === null,
        '同じ寸法なのに上書きと書いた');
  check(line({ width: 48, height: 48 }, { width: 48, height: 96 })
        === 'override=48x48->48x96', '高さだけの上書きを見ていない');
}

// ── ハッシュが動くこと ──────────────────────────────────────────
check(h('a') !== h('b'), 'ハッシュが別の文字列で同じ');
check(h('a') === h('a'), 'ハッシュが同じ文字列で違う');

// ── #145: 部品の器が、各変異の文字の段・実際の書体・寸法を出すか ─────────
{
  const frames = readFileSync(join(here, '..', 'exporters', 'export_frames.js'), 'utf8');
  const comps = readFileSync(join(here, '..', 'exporters', 'export_components.js'), 'utf8');
  const block = (t) => {
    const a = t.indexOf('function hex('), b = t.indexOf('\nasync function walk(');
    const e = t.indexOf('\n}\n', b);
    return a > 0 && b > a && e > b ? t.slice(a, e + 3) : null;
  };
  // 写しが離れると、画面と部品で行の形が変わる。**片方だけ直すと落とす**
  check(block(frames) !== null && block(frames) === block(comps),
        'export_components.js の行の関数が export_frames.js と食い違っている（両方を直す）');

  // 実際に回す。Figma を偽物にして、器を丸ごと評価する
  const text = (chars, segs) => ({
    type: 'TEXT', name: 'Label', characters: chars, width: 40, height: 16, x: 12, y: 4,
    textStyleId: 'S:caption1', textAlignHorizontal: 'LEFT',
    fontName: MIXED, fontSize: MIXED,           // 素で読むと Symbol（#32 の形）
    getStyledTextSegments: () => segs,
  });
  const variant = (name, t, w) => ({
    type: 'COMPONENT', name, id: 'v:' + name, width: w, height: 32, x: 0, y: 0,
    children: [t],
  });
  const seg = (style, size) => ({ fontName: { family: 'SF Pro', style }, fontSize: size });
  const mk = (variants) => {
    const set = { type: 'COMPONENT_SET', name: 'Chips/Text', id: '1:1', children: variants };
    for (const v of variants) { v.parent = set; for (const c of v.children) c.parent = v; }
    const page = {
      name: 'Comp', loadAsync: async () => {},
      findAllWithCriteria: ({ types }) => (types[0] === 'COMPONENT_SET' ? [set] : variants),
    };
    return {
      mixed: MIXED, root: { children: [page] },
      getStyleByIdAsync: async (id) => ({ name: id.replace('S:', '') }),
      variables: { getVariableByIdAsync: async () => null },
    };
  };
  const pre = src.replace(/^const ALLOW_PAGES[^\n]*$/m, "const ALLOW_PAGES = ['Comp'];");
  const AF = Object.getPrototypeOf(async function () {}).constructor;
  const run = async (fig) => JSON.parse(await new AF('figma', pre + '\n' + comps)(fig));

  const out = await run(mk([
    variant('State=On', text('ON', [seg('Regular', 13), seg('Bold', 13)]), 48),
    variant('State=Off', text('OFF', [seg('Regular', 13)]), 52),
  ]));
  const on = out.componentSets?.['Chips/Text']?.variants?.['State=On']?.rows || [];
  const off = out.componentSets?.['Chips/Text']?.variants?.['State=Off']?.rows || [];
  check(on.some((r) => r.includes('ts=caption1')), `文字の段（ts=）が出ていない: ${on}`);
  check(on.some((r) => r.includes('font=SF Pro/Regular/13+SF Pro/Bold/13')),
        `字ごとに違う書体を区間で出していない: ${on}`);
  check(off.some((r) => r.includes('font=SF Pro/Regular/13') && !r.includes('+')),
        `書体を 1 つにまとめていない: ${off}`);
  check(on[0]?.startsWith('0|State=On|COMPONENT|48|32'), `変異の寸法が 0 行目に無い: ${on[0]}`);
  check(off[0]?.startsWith('0|State=Off|COMPONENT|52|32'), '全部の変異を出していない');
  check(out.digest?.variants === 2, `変異の数を数えていない: ${out.digest?.variants}`);
  check(out.componentSets?.['Chips/Text']?.variantTotal === 2, '全部の変異の数（variantTotal）を書いていない');

  const dup = await run(mk([
    variant('State=On', text('A', [seg('Regular', 13)]), 48),
    variant('State=On', text('B', [seg('Regular', 13)]), 48),
  ]));
  check(dup.error === '同名の変異', '同じ名前の変異を黙って上書きした');
}

// ── #148 #149 #150 #152（2026-09-28）: 塗り・性質・上書き・区切り文字 ───────────
{
  const comps = readFileSync(join(here, '..', 'exporters', 'export_components.js'), 'utf8');
  const pre = src.replace(/^const ALLOW_PAGES[^\n]*$/m, "const ALLOW_PAGES = ['Comp'];");
  const AF = Object.getPrototypeOf(async function () {}).constructor;
  const VARS = { v5: 'Translucent/Black/5', v0: 'Translucent/Black/0', vt: 'Text/Inverse/Default' };
  const LS = String.fromCharCode(0x2028);            // Figma の Shift+Enter の改行
  const inst = { type: 'INSTANCE', name: 'Glyph', id: 'i1', width: 12, height: 12, x: 0, y: 0 };
  const glyphText = { type: 'TEXT', name: 'mark', id: 't1', parent: inst, characters: '★',
    textStyleId: null, textAlignHorizontal: 'LEFT', fontName: MIXED, fontSize: MIXED,
    fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }], boundVariables: { fills: [{ id: 'vt' }] },
    getStyledTextSegments: () => [{ fontName: { family: 'SF Pro', style: 'Light' }, fontSize: 17 }] };
  Object.assign(inst, {
    children: [glyphText],
    getMainComponentAsync: async () => ({ name: 'Size=small', width: 12, height: 12,
      variantProperties: { Size: 'small' }, parent: { type: 'COMPONENT_SET', name: 'Icon' } }),
    componentProperties: { 'Show#1:2': { type: 'BOOLEAN', value: true },
                           'Label#3:4': { type: 'TEXT', value: 'INTP | 論理学者' },
                           'Glyph#5:6': { type: 'INSTANCE_SWAP', value: '9:9' } },
    overrides: [{ id: 't1', overriddenFields: ['fills', 'name', 'boundVariables'] },
                { id: 'hidden', overriddenFields: ['fills'] }],
  });
  const grad = { type: 'RECTANGLE', name: 'Bg', id: 'r1', width: 390, height: 44, x: 0, y: 0,
    // **止め色に変数を結んだグラデーション**。boundVariables.fills に止め色の変数が出る（#149 の実害の形）
    fills: [{ type: 'GRADIENT_LINEAR', gradientStops: [
      { position: 0, color: { r: 0, g: 0, b: 0, a: 0.05 }, boundVariables: { color: { id: 'v5' } } },
      { position: 1, color: { r: 0, g: 0, b: 0, a: 0 }, boundVariables: { color: { id: 'v0' } } }] }],
    boundVariables: { fills: [{ id: 'v0' }] }, fillStyleId: 'S:Header',
    cornerRadius: MIXED, topLeftRadius: 24, topRightRadius: 24, bottomRightRadius: 0, bottomLeftRadius: 0 };
  const label = { type: 'TEXT', name: 'Label', id: 't2', width: 60, height: 16, x: 0, y: 0,
    characters: 'そうだね' + LS + '連絡しておく | 了解', textStyleId: 'S:body', textAlignHorizontal: 'LEFT',
    fontName: MIXED, fontSize: MIXED,
    getStyledTextSegments: () => [{ fontName: { family: 'SF Pro', style: 'Regular' }, fontSize: 13 }] };
  const variant = { type: 'COMPONENT', name: 'State=On', id: 'c1', width: 390, height: 44, x: 0, y: 0,
    children: [grad, label, inst] };
  const set = { type: 'COMPONENT_SET', name: 'Header', id: '1:1', children: [variant] };
  for (const c of variant.children) c.parent = variant;
  variant.parent = set;
  const page = { name: 'Comp', loadAsync: async () => {},
    findAllWithCriteria: ({ types }) => (types[0] === 'COMPONENT_SET' ? [set] : [variant]) };
  const nodes = { '9:9': { name: 'star' }, t1: glyphText };
  const fig = {
    mixed: MIXED, root: { children: [page] },
    getStyleByIdAsync: async (id) => ({ name: id.replace('S:', '') }),
    getNodeByIdAsync: async (id) => nodes[id] || null,
    variables: { getVariableByIdAsync: async (id) => (VARS[id] ? { name: VARS[id] } : null) },
  };
  const raw = await new AF('figma', pre + '\n' + comps)(fig);
  check(!raw.includes(LS), '#148: 戻しに U+2028 がそのまま残っている（転送が行の途中で切れる）');
  const out = JSON.parse(raw);
  const rows = out.componentSets?.Header?.variants?.['State=On']?.rows || [];
  const rowOf = (name) => rows.find((r) => r.split('|')[1] === name) || '';
  const bg = rowOf('Bg');
  check(bg.includes('fill=GRADIENT_LINEAR:Translucent/Black/5@0>Translucent/Black/0@1'),
        `#149: グラデーションを止め色つきで書いていない: ${bg}`);
  check(!/\|fill=Translucent\/Black\/0(\||$)/.test(bg), `#149: グラデーションが透明の単色に潰れた: ${bg}`);
  check(bg.includes('fillStyle=Header'), `#149: 塗りのスタイルを書いていない: ${bg}`);
  check(bg.includes('radius=24,24,0,0'), `#149: 角ごとの角丸を書いていない: ${bg}`);
  const lb = rowOf('Label');
  check(lb.split('|').length === rowOf('Label').split('|').length && lb.includes('text='),
        '文字の行が無い');
  const txt = lb.split('|').find((f) => f.startsWith('text='));
  check(txt && JSON.parse(txt.slice(5)) === 'そうだね' + LS + '連絡しておく | 了解',
        `#148/#150: 文字の | か区切り文字を戻せない（行が割れた）: ${txt}`);
  const gl = rowOf('Glyph');
  const propsF = gl.split('|').find((f) => f.startsWith('props='));
  const props = propsF ? JSON.parse(propsF.slice(6)) : {};
  check(props.Show === true && props.Label === 'INTP | 論理学者' && props.Glyph === 'star',
        `#150: インスタンスの性質の値を書いていない（#id を落とす・入れ替えは部品の名前）: ${propsF}`);
  const ovF = gl.split('|').find((f) => f.startsWith('ov='));
  const ov = ovF ? JSON.parse(ovF.slice(3)) : [];
  check(ov.some(([path, v]) => path === 'mark' && v && v.boundVariables && v.boundVariables.fills === 'Text/Inverse/Default'),
        `#152: 変数の結び付きの上書きを「あり」だけで済ませた（どの欄にどの変数か）: ${ovF}`);
  check(ov.some(([path, v]) => path === 'mark' && v && v.fills === 'Text/Inverse/Default' && !('name' in v)),
        `#152: 中の上書き（塗り）を書いていない、または名前の上書きを落としていない: ${ovF}`);
  const nr = out.$meta?.['読めなかったもの'] || [];
  check(nr.length === 1 && nr[0].instance === 'i1' && nr[0].fields.includes('fills'),
        `#152: 引けない上書きを「読めなかったもの」に並べていない: ${JSON.stringify(nr)}`);
  check(ov.some(([path]) => path === '?'), `#152: 引けない上書きを行から黙って落とした: ${ovF}`);
}

// ── 画面の器の戻し（2026-09-28）: ページ・節・版面の幅で選び、読めなかったものと FNV を付けて返す ──
{
  const frSrc = readFileSync(join(here, '..', 'exporters', 'export_frames.js'), 'utf8')
    .replace("const SECTIONS = ['{{節の名前}}'];", "const SECTIONS = ['Home'];")
    .replace("p.name === '{{ページ名}}'", "p.name === 'Designs'")
    .replace('{{版面の幅}}', '390');
  check(!frSrc.includes('{{'), '画面の器の置き換える所（ページ名・節・版面の幅）が試験と合っていない');
  const LS = String.fromCharCode(0x2028);
  const scr = { type: 'FRAME', name: 'Top', id: '5:1', width: 390, height: 844, x: 0, y: 0,
    children: [{ type: 'TEXT', name: 'Hello', id: '5:2', width: 100, height: 20, x: 0, y: 0,
                 characters: 'やあ' + LS + 'ね', textAlignHorizontal: 'LEFT',
                 getStyledTextSegments: () => [{ fontName: { family: 'SF Pro', style: 'Regular' }, fontSize: 17 }] }] };
  const small = { type: 'FRAME', name: 'UI Stack', id: '5:3', width: 390, height: 50, x: 0, y: 0, children: [] };
  const sec = { type: 'SECTION', name: 'Home', children: [scr, small] };
  const other = { type: 'SECTION', name: 'Other', children: [{ ...scr, id: '6:1', name: 'Else' }] };
  const fig = { mixed: MIXED, root: { children: [{ name: 'Designs', loadAsync: async () => {}, children: [sec, other] }] },
    getStyleByIdAsync: async () => null, getNodeByIdAsync: async () => null,
    variables: { getVariableByIdAsync: async () => null } };
  const AF = Object.getPrototypeOf(async function () {}).constructor;
  const raw = await new AF('figma', frSrc)(fig);
  check(!raw.includes(LS), '画面の器: 戻しに U+2028 がそのまま残っている（#148）');
  const got = JSON.parse(raw);
  check(Object.keys(got.frames || {}).join() === '5:1', `画面の器: 節と版面の幅で画面を選べていない: ${Object.keys(got.frames || {})}`);
  check(Array.isArray(got.$meta?.['読めなかったもの']), '画面の器: 戻しに「読めなかったもの」が無い（#152）');
  check(got.digest?.rows === 1 && typeof got.digest?.value === 'number', '画面の器: FNV の検査値が無い');
}

console.log(`preamble_test: ${ok ? 'OK' : 'NG'}（47 件）`);
process.exit(ok ? 0 : 1);
