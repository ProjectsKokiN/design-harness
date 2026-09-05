// 書き出し器の共通の前置き（2026-09-02 新設）。
//
// `use_figma` は**自己完結した1つのスクリプト**しか受け取らないので、
// 各書き出し器はこのファイルの中身を頭にそのまま貼る。import できない。
//
// ## なぜ要るか
//
// FlashEnglish / 414 の書き出し器は `COMPONENT_SET` しか集めていなかった。
//
//     page.findAllWithCriteria({ types: ['COMPONENT_SET'] })
//
// そのため単体の `COMPONENT`（Header / Footer / BottomNavigation / EmptyStates の
// 4件）が書き出しに1件も入らず、**条件7（Figma にあるものは全部実装する）の
// 分母が4件小さい**状態だった。しかも気づけない理由が3つ重なっていた。
//
//   (a) `$meta.declared` が**同じ間違った分母**を持つので受け入れ条件が通る
//   (b) `impl_coverage_check` が「対応表にあるのに書き出しに無い」と実装側を
//       疑う形で報告し、**実装を削る方向へ誘導する**
//   (c) 条件4・条件5 も同じ書き出しを読むので、4件はどの検査からも見えない
//
// aub-familywalk は単体を拾えていたが、**手で保守するノード番号の表**
// （`_ids.md` の `IDS`）を持つ形だった。表そのものが手写しの層なので、
// ここでは**ページを歩いて器が数える**形にする。
//
// ## 決まり
//
//   - **許可リスト方式**（除外方式にしない）。除外方式だと Figma に新しい
//     ページが増えたとき黙って書き出しに入る
//   - **件数は器が数えて書く。** 手で書いた分母は必ずずれる
//   - **同名があれば止める。** どちらが正かは機械で決められない。黙って
//     上書きすると、1件が別物にすり替わったまま下流の照合が全部通る
//   - **許可ページが1枚も無ければ止める。** 空の書き出しを返すと
//     「Figma が空」に見える

/** 参照してよいページ。案件の design/figma/page-scope.json の allowed と揃える。 */
const ALLOW_PAGES = ['⚙️_Styles&Components'];   // ← 案件ごとに書き換える

/**
 * 値を1つ安全に読む。**`figma.mixed` を文字列に入れない。**
 *
 * 実害（qnd-database・2026-09-03・#32）: Footer が辺ごとに違う線の太さを
 * 持っており `strokeWeight` が `figma.mixed`（Symbol）を返した。それを
 * テンプレート文字列に入れた瞬間 `TypeError: cannot convert symbol to string`
 * で**書き出しごと止まり、12部品のうち1件も取れなかった**。
 * `cornerRadius` には mixed の処理があったのに `strokeWeight` には無く、
 * **同じ形の抜け**だった。だから**キーごとに書かず、ここを通す。**
 *
 * 戻り: 値 / `'MIXED'` / `null`（無い・読めない）
 */
function val(n, key) {
  let v;
  try { v = n[key]; } catch (e) { return null; }   // getter が投げるノードがある
  if (typeof v === 'symbol') return 'MIXED';       // figma.mixed
  return v === undefined ? null : v;
}

/** 数として読む。mixed と不在はそのまま返す（数に潰さない）。 */
function num(n, key) {
  const v = val(n, key);
  return typeof v === 'number' ? Math.round(v * 100) / 100 : v;
}

/**
 * 重なり順の指定（`itemReverseZIndex`）。**意味に翻訳せず生の真偽値を返す。**
 *
 * 実害（FlashEnglish・2026-09-03・#10）: これが書き出しに無かったため、
 * AI が `children` の並びだけで重なり順を判断し、**「Figma が壊れている」と
 * 誤報**した（実際は正しかった）。`children` は**並び順であって描画順ではない**。
 *
 * **`true` / `false` がどちらの向きかをここで決めない。** 翻訳を挟むと
 * それが「正」になる（`counterAxisAlignItems: MAX` を "bottom" と書き写した
 * 前例がある）。読む側が Figma の画面と突き合わせる。
 */
function revZ(n) {
  const v = val(n, 'itemReverseZIndex');
  return typeof v === 'boolean' ? v : null;
}

/** 指紋。**気づくためだけの値**なので暗号強度は要らない（FNV-1a 32bit）。 */
function h(s) {
  let x = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    x ^= s.charCodeAt(i) & 0xFF;
    x = (x + ((x << 1) + (x << 4) + (x << 7) + (x << 8) + (x << 24))) >>> 0;
  }
  return x >>> 0;
}

/**
 * 許可ページを歩いて、component set と**単体 component** を集める。
 *
 * 単体の判定: 親が COMPONENT_SET でない COMPONENT。
 * （COMPONENT_SET の子は「バリアント」であって単体ではない）
 *
 * 戻り: { sets, singles, pages, declared } または { error, ... }
 */
async function collect() {
  const sets = new Map();
  const singles = new Map();
  const dup = [];
  const seenPages = [];

  for (const page of figma.root.children) {
    if (!ALLOW_PAGES.includes(page.name)) continue;
    seenPages.push(page.name);
    await page.loadAsync();

    for (const n of page.findAllWithCriteria({ types: ['COMPONENT_SET'] })) {
      if (sets.has(n.name) || singles.has(n.name)) dup.push(n.name);
      sets.set(n.name, n);
    }
    // **単体の COMPONENT も集める**（2026-09-02。ここが抜けていた）
    for (const n of page.findAllWithCriteria({ types: ['COMPONENT'] })) {
      if (n.parent && n.parent.type === 'COMPONENT_SET') continue;   // バリアント
      if (sets.has(n.name) || singles.has(n.name)) dup.push(n.name);
      singles.set(n.name, n);
    }
  }

  if (!seenPages.length) {
    return { error: '許可ページが見つからない', allow: ALLOW_PAGES,
             actual: figma.root.children.map((p) => p.name) };
  }
  if (dup.length) {
    // どちらが正かは機械で決められない。**止めて報告する。**
    const where = [...new Set(dup)].map((name) => {
      const hits = [];
      for (const [m, list] of [['set', sets], ['single', singles]]) {
        const n = list.get(name);
        if (n) hits.push(`${m}:${n.id}`);
      }
      return `${name}(${hits.join(' ')})`;
    });
    return { error: '同名のコンポーネント', names: where };
  }

  return {
    sets, singles, pages: seenPages,
    // **器が数える。** 手で書いた分母は必ずずれる
    declared: { componentSets: sets.size, singleComponents: singles.size,
                pages: seenPages.length },
  };
}
