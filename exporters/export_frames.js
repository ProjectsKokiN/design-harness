// frames.json を作る。**画面のノード木の機械書き出し。**
//
// 2026-09-04 に aub-familywalk から回収した（#14）。
// `production-gate.md` は「画面固有の値の照合先は figma/frames.json（画面の
// ノード木の機械書き出し）。これが無い案件は記録層を消せない」と書いていたのに、
// **その書き出し器が共有層に無かった。** aub には在り、414 と flash-compose には
// 無い（414 の frames.json は `surfaces`＝部品にならない枠で、画面ではない）。
//
// 結果、flash-compose の手書きの記録層は 63 件 assert したまま残り、
// **そのうち置き換えられるのは 9 件だけ**だった。残り 54 件はほぼ全部が
// 画面固有の値（body.margin / Illusts.* / QuizScreen.* / MyPage.*）で、
// **照合先が存在しなかった。** 「記録層を廃止する」という 2026-08-29 の決定は、
// 画面の値については**実行不可能**だった。決定から5日、誰も気づいていない。
//
// 案件ごとに書き換えるのは末尾の4つ（PAGE / SECTIONS / ONLY_IDS / 画面の見分け方）。
// 前提条件が満たせているかは `tools/screen_export_check.py` が測る。
// **「在る」と「足りている」は違う**（flash-compose は 3 件の frames.json を
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
async function sn(id) {
  if (!id || id === figma.mixed) return null;
  const s = await figma.getStyleByIdAsync(id);
  return s ? s.name : null;
}
/** そのノードの「形」（位置を除いた全部）を1行で返す */
async function shape(n) {
  const p = [];
  if (n.visible === false) p.push('vis=0');
  if (n.opacity != null && n.opacity !== 1) p.push('opacity=' + R(n.opacity));
  // **見えている塗りを全部書く。** 2026-08-30 まで fills[0] だけを見て、
  // しかも変数名を優先していたため、Splash の
  // 「グラデーション＋画像」の画像が隠れていた（白地に白のロゴに見えた）。
  if (n.fills && n.fills !== figma.mixed && n.fills.length) {
    const vis = n.fills.filter(f => f.visible !== false);
    if (vis.length) {
      const v = await bn(n, 'fills');
      p.push('fill=' + (vis.length === 1 && v ? v
        : vis.map(f => f.type
            + (f.color ? ':' + hex(f.color) : '')
            + (f.imageHash ? ':' + f.imageHash.slice(0, 8) : '')).join('+')));
    }
  }
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
  if (n.cornerRadius != null && n.cornerRadius !== figma.mixed && n.cornerRadius !== 0) {
    p.push('radius=' + (await bn(n, 'topLeftRadius') || R(n.cornerRadius)));
  }
  if (n.type === 'TEXT') {
    p.push('text=' + JSON.stringify(n.characters));
    const ts = await sn(n.textStyleId); if (ts) p.push('ts=' + ts);
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
return JSON.stringify({ frames: out,
  digest: { algo: 'FNV-1a 32bit', rows: Object.keys(out).length, chars: body.length, value: h(body) } });
