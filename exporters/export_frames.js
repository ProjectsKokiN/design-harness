// frames.json を作る。**画面のノード木の機械書き出し。**
//
// 2026-09-04 に aub-familywalk から回収した（#14）。
// `production-gate.md` は「画面固有の値の照合先は figma/frames.json（画面の
// ノード木の機械書き出し）。これが無い案件は記録層を消せない」と書いていたのに、
// **その書き出し器が共有層に無かった。** aub には在り、414 と FlashEnglish には
// 無い（414 の frames.json は `surfaces`＝部品にならない枠で、画面ではない）。
//
// 結果、FlashEnglish の手書きの記録層は 63 件 assert したまま残り、
// **そのうち置き換えられるのは 9 件だけ**だった。残り 54 件はほぼ全部が
// 画面固有の値（body.margin / Illusts.* / QuizScreen.* / MyPage.*）で、
// **照合先が存在しなかった。** 「記録層を廃止する」という 2026-08-29 の決定は、
// 画面の値については**実行不可能**だった。決定から5日、誰も気づいていない。
//
// 案件ごとに書き換えるのは末尾の4つ（PAGE / SECTIONS / ONLY_IDS / 画面の見分け方）。
// 前提条件が満たせているかは `tools/screen_export_check.py` が測る。
// **「在る」と「足りている」は違う**（FlashEnglish は 3 件の frames.json を
// 持っていたので、前提条件を満たしているように見えていた）。
//
// 出すもの: design/screens.json に並べた画面の全部。
// **行形式で返す**（JSON はキーの繰り返しで嵩み、20KB で切られる。2026-08-30 実測）。
//
//   1行 = 深さ|名前|型|w|h|x|y|k=v|k=v...
//
// 読み取りの決まり:
//   - 部品のインスタンスは `instanceOf`（セット名とバリアント）まで。**中には降りない**
//     （部品の仕様は ⚙️_Styles&Components の定義ノードが正。画面は使われ方だけ）
//   - **ただし寸法は画面が正。** 定義と実寸が違えば `override=48x48->360x360` を足す
//     （余白・すき間・塗り・角丸・文字スタイルは定義が正。寸法と伸び方だけ画面が正）
//   - 色・文字スタイル・効果は**変数／スタイルの名前**で書く。解決しない
//   - **ただし文字は実際の書体と大きさも書く**（`font=SF Pro/Regular/13`。#145）。
//     スタイル名だけだと、スタイルの中身が変わったことに行から気づけない
//
// 2026-09-28 に足した欄（PlantTalk のレジストリの器から回収。**今までの欄は変えていない**）:
//   - `fill=` … **変数の名前だけで書くのは、塗りが 1 つで単色のときだけ**。グラデーションは
//     止め色を `変数名か#hex@位置` にして `>` でつなぐ（#149。止め色に変数を結んだ
//     グラデーションが `fill=<変数名>`＝透明の単色に潰れていた）
//   - `fillStyle=` … 塗りのスタイルの名前（#149。それまでどこでも読んでいなかった）
//   - `radius=左上,右上,右下,左下` … 角ごとに違うとき（#149。それまで何も書かなかった）
//   - `props=` … インスタンスの性質の値（BOOLEAN / TEXT / INSTANCE_SWAP。名前の #id は落とす。#150）
//   - `ov=` … インスタンスの中で上書きした欄と値（`[[中の経路, {欄: 値}], …]`。#152）。
//     引けない上書き（隠れた子への上書きなど）は `$meta.読めなかったもの` に並べる。
//     案件は pack で notcaptured.json の「読めなかったもの」へ写す
//   - JSON を入れる欄（`text=` `props=` `ov=`）では、行の区切りの `|` を JSON の書き方で逃がす
//
// **戻しが失われる形は 2 つあり、見分けられる**（#148）:
//   - **丸ごと失われる**: 文字に U+2028 / U+2029 / U+0085（Figma の Shift+Enter の改行など）が
//     入っていると、use_figma の転送が行の途中で切れ、`Failed to parse SSE message … EOF while
//     parsing a string` になる。**大きさに関係なく、その画面は何度回しても落ちる。**
//     返す直前に JSON の書き方で逃がす（`safe()`）。JSON として読めば元の文字に戻る
//   - **切り詰めて返る**: 20KB を超えると `// truncated to 20kb` が付いて返る。ONLY_IDS で分ける
//   - **同じ形の兄弟は畳む**（ビンゴの 5x5 は 25 行ではなく 1 行 + 位置の列）
function h(s){let x=0x811c9dc5;for(let i=0;i<s.length;i++){x^=s.charCodeAt(i)&0xFF;x=(x+((x<<1)+(x<<4)+(x<<7)+(x<<8)+(x<<24)))>>>0;}return x>>>0;}
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
const SECTIONS = ['{{節の名前}}'];   // ← ここを書き換えて複数回まわす
// 1枚だけ回したいとき（節が 20KB に収まらないとき）。空なら節の全部。
const ONLY_IDS = [];
const page = figma.root.children.find(p => p.name === '{{ページ名}}');
await page.loadAsync();
const out = {};
for (const sec of page.children) {
  if (sec.type !== 'SECTION' || !SECTIONS.includes(sec.name)) continue;
  for (const fr of sec.children) {
    // 画面の見分け方。案件の版面の幅に書き換える
    if (fr.type !== 'FRAME' || Math.round(fr.width) !== {{版面の幅}} || fr.height <= 60) continue;
    if (ONLY_IDS.length && !ONLY_IDS.includes(fr.id)) continue;
    const rows = [];
    await walk(fr, 0, rows);
    out[fr.id] = { section: sec.name, name: fr.name, rows };
  }
}
const body = JSON.stringify(out);
// **区切り文字を逃がして返す**（#148）。FNV は元の文字で取ってある（JSON として読めば元に戻る）
return safe(JSON.stringify({ frames: out,
  $meta: { 読めなかったもの: NOT_READ },
  digest: { algo: 'FNV-1a 32bit', rows: Object.keys(out).length, chars: body.length, value: h(body) } }));
