// components.json の本体を作る。**部品の各変異の中身を、行の形で書き出す。**
//
// 2026-09-25 新設（#145）。それまで部品の書き出し器が共有層に無く、PlantTalk の
// components.json は `variants`（数）・`variantAxes`・`properties` しか持って
// いなかった。**部品の中の文字の段と寸法がどこにも無く**、Chip の段が
// caption2 → caption1 に変わったことを部品の定義の側では確かめられなかった
// （画面の行の高さ 13 → 16 から導いて確かめた）。**画面に出ていない変異の変更は、
// どこからも見えなかった。**
//
// ## 使い方
//
// 1. **頭に `_preamble.js` の中身を貼る**（`use_figma` は import できない）。
//    `ALLOW_PAGES` を案件の page-scope.json の allowed にそろえる
// 2. 大きい案件は 20KB で切られるので、`ONLY` にセットの名前を入れて分けて回す。
//    1 セットでも収まらなければ `VARIANT_SLICE` で変異を区切る（PlantTalk の
//    Chips/Text は 126 変異で 77KB あった。2026-09-25 実測）
// 3. 返ってきた `componentSets` を案件の pack で components.json に差し込む
//
// ## 出すもの
//
//   componentSets: { <セット名>: { id, kind: 'set'|'single',
//                    variants: { <変異名>: { id, rows: [...] } } } }
//
//   1行 = 深さ|名前|型|w|h|x|y|k=v|k=v...（`export_frames.js` と同じ形）
//
//   - 深さ 0 の行が変異そのもの。**w|h がその変異の寸法**
//   - 文字は `ts=`（スタイル名）と `font=`（**実際の**書体/太さ/大きさ）の両方
//   - 部品の中の別の部品（インスタンス）は `of=` まで。**中には降りない**
//     （その部品の定義が、自分の行として別に出る）
//   - **全部の変異を出す。**見本を 1 変異で済ませると、変異によって在ったり
//     無かったりする子が消える（#22）
//
// ## 下の関数について
//
// `hex` から `walk` までは **`export_frames.js` から写したもの**（同じ形の行を出すため）。
// 2026-09-28 に塗り（グラデーション・塗りのスタイル・角ごとの角丸・#149）・インスタンスの
// 性質の値（props=・#150）・中の上書き（ov=・#152）・区切り文字の逃がし（#148）を足した。
// **部品の定義の中のインスタンスの上書き**（アイコンの塗り・書体など）は ov= に出る。
// 引けない上書きは `$meta.読めなかったもの` に並ぶので、pack で notcaptured.json の
// 「読めなかったもの」へ写す
// 直すときは両方を直す。`attack/preamble_test.mjs`（CI で回る）が食い違いを落とす。

// ── ここに _preamble.js の中身を貼る ──

function hex(c){const b=x=>Math.round(x*255).toString(16).padStart(2,'0');const a=c.a==null?1:c.a;return '#'+b(c.r)+b(c.g)+b(c.b)+(a===1?'':b(a));}
const R = x => x == null ? null : Math.round(x * 100) / 100;
async function bn(n, f) {
  const bv = n.boundVariables && n.boundVariables[f];
  const e = Array.isArray(bv) ? bv[0] : bv;
  if (!e) return null;
  const v = await figma.variables.getVariableByIdAsync(e.id);
  return v ? v.name : null;
}
/**
 * 文字の**実際の**書体と大きさ（#145・2026-09-25）。字ごとに違えば区間を + でつなぐ。
 *
 * それまで `ts=`（スタイル名）だけを書いていた。**スタイルの中身が変わっても行は
 * 変わらない**ので、Chip の段が caption2 → caption1 に変わったことを、PlantTalk は
 * 行の高さ（13 → 16）から**導いて**確かめていた。
 *
 * `getStyledTextSegments` は figma.mixed を返さない。素の `fontName` / `fontSize` は
 * 字ごとに違うと Symbol を返し、書き出しごと止まる（#32 と同じ形）ので読まない。
 */
function fontOf(n) {
  const seen = [];
  for (const seg of n.getStyledTextSegments(['fontName', 'fontSize'])) {
    const { fontName: f, fontSize: z } = seg;
    const k = f.family + '/' + f.style + '/' + R(z);
    if (!seen.includes(k)) seen.push(k);
  }
  return seen.join('+');
}
/** 値を1つ安全に読む（_preamble.js の val と同じ働き。**この器は前置きを貼らない**ので、ここにも持つ。
 *  部品の器は前置きを貼るので、名前をずらしてある）。figma.mixed は 'MIXED'、無い・読めないは null */
function rv(n, key) {
  let v;
  try { v = n[key]; } catch (e) { return null; }
  if (typeof v === 'symbol') return 'MIXED';
  return v === undefined ? null : v;
}
const rn = (n, key) => { const v = rv(n, key); return typeof v === 'number' ? R(v) : v; };
async function sn(id) {
  if (!id || id === figma.mixed || id === 'MIXED') return null;
  const s = await figma.getStyleByIdAsync(id);
  return s ? s.name : null;
}
/** 行の区切り（|）を JSON の欄の中に入れない（#150・#152）。逃がした形は JSON の書き方なので、
 *  読む側が JSON として読めば元に戻る。**逃がした形をコードに直に書かない**（use_figma に渡す途中で
 *  文字に戻される。#148） */
const BS = String.fromCharCode(92);
const esc = t => t.split('|').join(BS + 'u007c');
/** 戻しの区切り文字（U+2028 / U+2029 / U+0085）を JSON の書き方で逃がす（#148） */
function safe(t) {
  let out = '';
  for (let i = 0; i < t.length; i++) {
    const c = t.charCodeAt(i);
    out += (c === 0x2028 || c === 0x2029 || c === 0x85) ? BS + 'u' + c.toString(16).padStart(4, '0') : t[i];
  }
  return out;
}
/** 書き出せなかったもの。器の戻しの `$meta.読めなかったもの` に入れる（#152）。
 *  **同じものを 2 回並べない**（形は行を書くときと、兄弟を畳むために比べるときの 2 回作る） */
const NOT_READ = [];
const NOT_READ_SEEN = new Set();
/** 塗り 1 つ（#149）。単色は変数の名前（無ければ SOLID:#hex）、グラデーションは止め色を
 *  `変数名か#hex@位置` にして `>` でつなぐ、画像はハッシュの頭 8 桁 */
async function paintOf(f) {
  const vn = async a => {
    if (!a) return null;
    const v = await figma.variables.getVariableByIdAsync(a.id);
    return v ? v.name : null;
  };
  if (f.type === 'SOLID') return (await vn(f.boundVariables && f.boundVariables.color)) || ('SOLID:' + hex(f.color));
  if (f.type.startsWith('GRADIENT')) {
    const st = [];
    for (const g of f.gradientStops || []) st.push(((await vn(g.boundVariables && g.boundVariables.color)) || hex(g.color)) + '@' + R(g.position));
    return f.type + ':' + st.join('>');
  }
  return f.type + (f.imageHash ? ':' + f.imageHash.slice(0, 8) : '');
}
/** 見えている塗りを全部書く。**変数の名前だけで書くのは、塗りが 1 つで単色のときだけ**（#149） */
async function fillsOf(n) {
  const fl = rv(n, 'fills');
  if (!Array.isArray(fl) || !fl.length) return null;
  const vis = fl.filter(f => f.visible !== false);
  if (!vis.length) return null;
  const v = await bn(n, 'fills');
  if (vis.length === 1 && vis[0].type === 'SOLID' && v) return v;
  const parts = [];
  for (const f of vis) parts.push(await paintOf(f));
  return parts.join('+');
}
/** インスタンスの性質の値（#150）。VARIANT は of= に出すので書かない。名前の #id は落とす */
async function propsOf(n) {
  const props = {};
  for (const [k, v] of Object.entries(n.componentProperties || {})) {
    const key = k.replace(/#[^#]*$/, '');
    if (v.type === 'BOOLEAN' || v.type === 'TEXT') props[key] = v.value;
    else if (v.type === 'INSTANCE_SWAP') {
      const c = await figma.getNodeByIdAsync(v.value);
      props[key] = c ? c.name : v.value;
    }
  }
  return props;
}
/** 上書きされた欄 1 つの、いまの値（ov= に入れる）。**意味に翻訳しない**（Figma の欄の名前と値のまま） */
async function ovValue(node, f) {
  switch (f) {
    case 'characters': return node.characters;
    case 'fills': return await fillsOf(node);
    case 'strokes': return (await bn(node, 'strokes')) || ((rv(node, 'strokes') || []).length ? 'あり' : null);
    case 'componentProperties': return await propsOf(node);
    case 'textStyleId': case 'fillStyleId': case 'strokeStyleId': case 'effectStyleId': return await sn(rv(node, f));
    case 'fontName': case 'fontSize': return node.type === 'TEXT' ? fontOf(node) : null;
    case 'boundVariables': {
      // どの欄にどの変数を結んだか（「あり」だけでは、上書きの中身が分からない）
      const out = {};
      for (const [k, v] of Object.entries(node.boundVariables || {})) {
        const e = Array.isArray(v) ? v[0] : v;
        if (!e || !e.id) continue;
        const x = await figma.variables.getVariableByIdAsync(e.id);
        out[k] = x ? x.name : '?';
      }
      return out;
    }
    default: {
      const v = rv(node, f);
      if (typeof v === 'number') return R(v);
      if (typeof v === 'string' || typeof v === 'boolean' || v === null) return v;
      return 'あり';
    }
  }
}
/** インスタンスの中で上書きした欄と値（#152）。名前と位置の上書きは落とす（形に効かない）。
 *  **引けない上書きは行に ? で残し、`$meta.読めなかったもの` にも並べる**（黙って落とさない） */
async function overridesOf(n) {
  const ovs = [];
  for (const o of (n.overrides || [])) {
    const node = await figma.getNodeByIdAsync(o.id);
    if (!node) {
      ovs.push(['?', o.overriddenFields.join('+')]);
      if (!NOT_READ_SEEN.has(n.id + '|' + o.id)) {
        NOT_READ_SEEN.add(n.id + '|' + o.id);
        NOT_READ.push({ instance: n.id, name: n.name, fields: o.overriddenFields,
                        why: 'ノードが引けない（隠れた子への上書きなど。skipInvisibleInstanceChildren）' });
      }
      continue;
    }
    const path = [];
    let cur = node;
    while (cur && cur.id !== n.id) { path.unshift(cur.name); cur = cur.parent; }
    const vals = {};
    for (const f of o.overriddenFields) {
      if (['name', 'x', 'y', 'relativeTransform', 'pluginData', 'autoRename', 'expanded'].includes(f)) continue;
      vals[f] = await ovValue(node, f);
    }
    if (Object.keys(vals).length) ovs.push([path.join('/'), vals]);
  }
  return ovs;
}
/** そのノードの「形」（位置を除いた全部）を1行で返す */
async function shape(n) {
  const p = [];
  if (n.visible === false) p.push('vis=0');
  if (n.opacity != null && n.opacity !== 1) p.push('opacity=' + R(n.opacity));
  // **見えている塗りを全部書く。** 2026-08-30 まで fills[0] だけを見て、
  // しかも変数名を優先していたため、Splash の
  // 「グラデーション＋画像」の画像が隠れていた（白地に白のロゴに見えた）。
  //
  // **変数の名前だけで書くのは、塗りが 1 つで単色のときだけ**（#149・2026-09-28）。
  // 止め色に変数を結んだグラデーションは boundVariables.fills に止め色の変数が出るため、
  // 「塗りが 1 つで変数がある」だけを見ていると `fill=Translucent/Black/0`（透明の単色）に潰れた
  // （PlantTalk の Header / Footer 53 か所。字どおりに読むとヘッダーの背景を透明にしてしまう）
  const fl = await fillsOf(n); if (fl) p.push('fill=' + fl);
  // **塗りのスタイル**（#149）。それまで書いておらず、Header / Footer の塗りのスタイルが行から消えていた
  const fst = await sn(rv(n, 'fillStyleId')); if (fst) p.push('fillStyle=' + fst);
  if (n.strokes && n.strokes.length) p.push('stroke=' + (await bn(n, 'strokes') || 'あり'));
  const es = await sn(n.effectStyleId); if (es) p.push('effect=' + es);
  if (n.layoutMode && n.layoutMode !== 'NONE') {
    p.push('layout=' + [n.paddingTop, n.paddingRight, n.paddingBottom, n.paddingLeft,
      n.itemSpacing, n.layoutMode,
      n.primaryAxisSizingMode === 'AUTO' ? 'HUG' : 'FIXED',
      n.counterAxisSizingMode === 'AUTO' ? 'HUG' : 'FIXED',
      n.primaryAxisAlignItems, n.counterAxisAlignItems].join(','));
  }
  // **親が Auto Layout のときの伸び方**（FILL / HUG / FIXED）。
  //
  // 2026-09-02 まで書いていなかった。`layout=` は**その節点が親として**
  // 子をどう並べるかで、**その節点が親の中でどう伸びるか**とは別の話。
  // そのため「画面幅いっぱいに伸びる」が書き出しに1件も入っておらず、
  // 実装は 390 で測った固定値を写していた（実機で 14 件のずれ。issue #8）。
  const par = n.parent;
  if (par && par.layoutMode && par.layoutMode !== 'NONE' &&
      'layoutSizingHorizontal' in n) {
    p.push('sz=' + n.layoutSizingHorizontal + ',' + n.layoutSizingVertical);
  }
  // **角ごとに違う角丸も書く**（#149・2026-09-28）。それまで figma.mixed のときは何も書かず、
  // 下から出るシート 8 枚（上だけ XXXL・下は 0）の角丸が行から消えていた。左上・右上・右下・左下の順
  const cr = rv(n, 'cornerRadius');
  if (cr === 'MIXED') {
    const c = [];
    for (const k of ['topLeftRadius', 'topRightRadius', 'bottomRightRadius', 'bottomLeftRadius']) c.push((await bn(n, k)) || rn(n, k));
    p.push('radius=' + c.join(','));
  } else if (cr != null && cr !== 0) {
    p.push('radius=' + (await bn(n, 'topLeftRadius') || R(cr)));
  }
  if (n.type === 'TEXT') {
    p.push('text=' + esc(JSON.stringify(n.characters)));   // | を逃がす（行が割れない）
    const ts = await sn(rv(n, 'textStyleId')); if (ts) p.push('ts=' + ts);
    const fo = fontOf(n); if (fo) p.push('font=' + fo);   // 書体/太さ/大きさ（#145）
    p.push('align=' + n.textAlignHorizontal);
  }
  if (n.type === 'INSTANCE') {
    const m = await n.getMainComponentAsync();
    if (m) {
      const set = (m.parent && m.parent.type === 'COMPONENT_SET') ? m.parent.name : m.name;
      p.push('of=' + set + (m.variantProperties ? '/' + Object.values(m.variantProperties).join(',') : ''));
      if (m.remote) p.push('remote=1');
      // **画面が寸法を上書きしていたら、そう書く**（2026-09-04・#26）。
      //
      // インスタンスは `of=` で止めて中に降りない。それは正しい方針だが、
      // **寸法だけは画面が正**（Figma でインスタンスの寸法は上書きできる）。
      // 上書きが行に出ないと、読む側は部品の定義の固定値を写す。
      //
      // aub の実害: `Images` の定義は固定 48。カメラは 360、スクラップボードは
      // 334、ALBUM は別の値で上書きしていた。**画面が全部 48 で描かれ、
      // 写真が潰れた。** 定義と実寸の両方が行にあれば気づける。
      if (R(m.width) !== R(n.width) || R(m.height) !== R(n.height)) {
        p.push('override=' + R(m.width) + 'x' + R(m.height) +
               '->' + R(n.width) + 'x' + R(n.height));
      }
    } else p.push('of=?');
    // **インスタンスの性質の値**（#150・2026-09-28）。中へは降りないので、表示の切り替え
    // （ShowSlot* / ShowChips*）と文字（TextChip など）がそれまで行に 1 つも無かった
    const props = await propsOf(n);
    if (Object.keys(props).length) p.push('props=' + esc(JSON.stringify(props)));
    // **中で上書きした欄と値**（#152・2026-09-28）。部品の中のアイコンの塗り・書体の上書きが
    // どこにも無かった（PlantTalk の Chips/Plain・Chips/Text の Icon 396 個）
    const ovs = await overridesOf(n);
    if (ovs.length) p.push('ov=' + esc(JSON.stringify(ovs)));
  }
  return p.join('|');
}
async function walk(n, depth, rows) {
  const sh = await shape(n);
  rows.push([depth, n.name, n.type, R(n.width), R(n.height), R(n.x), R(n.y)].join('|') + (sh ? '|' + sh : ''));
  if (n.type === 'INSTANCE' || !n.children || !n.children.length || depth >= 8) return;
  // 同じ形の兄弟を畳む
  const shapes = [];
  for (const c of n.children) shapes.push(await shape(c));
  let i = 0;
  while (i < n.children.length) {
    let j = i;
    while (j + 1 < n.children.length &&
           n.children[j + 1].type === n.children[i].type &&
           shapes[j + 1] === shapes[i] &&
           R(n.children[j + 1].width) === R(n.children[i].width) &&
           (!n.children[i].children || !n.children[i].children.length)) j++;
    if (j > i) {
      const pos = n.children.slice(i, j + 1).map(c => R(c.x) + ',' + R(c.y)).join(' ');
      rows.push([depth + 1, n.children[i].name + '×' + (j - i + 1), n.children[i].type,
        R(n.children[i].width), R(n.children[i].height), '-', '-'].join('|') +
        (shapes[i] ? '|' + shapes[i] : '') + '|at=' + pos);
    } else {
      await walk(n.children[i], depth + 1, rows);
    }
    i = j + 1;
  }
}

// 20KB で切られるときは、セットの名前で分けて複数回まわす。空なら全部
const ONLY = [];
// 1 セットでも収まらないときは変異を区切る（[始め, 終わり)）。既定は全部
const VARIANT_SLICE = [0, Infinity];

const c = await collect();
if (c.error) return safe(JSON.stringify(c));    // 止める（同名・許可ページ無し）

const out = {};
const dupVariants = [];
for (const [kind, list] of [['set', c.sets], ['single', c.singles]]) {
  for (const [name, node] of list) {
    if (ONLY.length && !ONLY.includes(name)) continue;
    const variants = {};
    const all = kind === 'set' ? node.children.filter((v) => v.type === 'COMPONENT') : [node];
    const vs = all.slice(VARIANT_SLICE[0], VARIANT_SLICE[1]);
    for (const v of vs) {
      const key = kind === 'set' ? v.name : '-';
      // 同じ名前の変異は、どちらが正か機械で決められない。**黙って上書きしない**
      if (variants[key]) { dupVariants.push(name + '/' + key); continue; }
      const rows = [];
      await walk(v, 0, rows);
      variants[key] = { id: v.id, rows };
    }
    // **全部で何変異あるかを書く。**区切って回したとき、足りているかを数で確かめるため
    out[name] = { id: node.id, kind, variantTotal: all.length, variants };
  }
}
if (dupVariants.length) return safe(JSON.stringify({ error: '同名の変異', names: dupVariants }));

const body = JSON.stringify(out);
// **区切り文字を逃がして返す**（#148）。JSON として読めば元の文字に戻る
return safe(JSON.stringify({
  $meta: { declared: c.declared, pages: c.pages, only: ONLY,
           variantSlice: [VARIANT_SLICE[0], VARIANT_SLICE[1] === Infinity ? null : VARIANT_SLICE[1]],
           読めなかったもの: NOT_READ },
  componentSets: out,
  digest: { algo: 'FNV-1a 32bit', sets: Object.keys(out).length,
            variants: Object.values(out).reduce((a, s) => a + Object.keys(s.variants).length, 0),
            chars: body.length, value: h(body) },
}));
