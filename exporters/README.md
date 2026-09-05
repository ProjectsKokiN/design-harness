# 書き出し器のひな形

`use_figma` は自己完結した1つのスクリプトしか受け取らないので、**import できません。**
各書き出し器は `_preamble.js` の中身を頭にそのまま貼ります。

## 使い方

```js
// …_preamble.js の中身…（ALLOW_PAGES を案件のページ名に書き換える）

const c = await collect();
if (c.error) return JSON.stringify(c);          // 止める（同名・許可ページ無し）

const result = {};
for (const [name, node] of [...c.sets, ...c.singles]) {
  result[name] = /* ここで読み取る */;
}
return JSON.stringify({ $meta: { declared: c.declared, pages: c.pages }, result });
```

## 置いてある器

| 器 | 出すもの |
|---|---|
| `export_frames.js` | **画面のノード木**（1行 = 深さ\|名前\|型\|w\|h\|x\|y\|k=v…）。行形式なのは JSON がキーの繰り返しで嵩み、20KB で切られるため |

`export_frames.js` の決まり:

- 部品のインスタンスは `instanceOf`（セット名とバリアント）まで。**中には降りない**
- 色・文字スタイル・効果は**変数／スタイルの名前**で書く。**解決しない**
  （`counterAxisAlignItems: MAX` を `"bottom"` と書き写すような翻訳を挟むと、
  **それが「正」になる**）
- **同じ形の兄弟は畳む**（ビンゴの 5x5 は 25 行ではなく 1 行 + 位置の列）

## 器を書くときの決まり

- **`figma.mixed` を素で読まない。** `val(n, key)` / `num(n, key)` を通す
  （#32: 辺ごとに違う線の太さで書き出しごと止まり、12部品のうち1件も取れなかった）
- **画面をたどるなら再帰にする。** 直下の子だけを見ると、1段深いところ
  （ダイアログの中のボタンなど）が黙って漏れる。**インスタンスに出会ったら止める**
  （#48: 4画面すべてで0行だった）
- **数えた画面の数を `$meta` に書く。** 器が「31画面のうち20画面ぶん」と
  自分で言えていても、突き合わせる検査が無ければ誰も気づかない
- **見本は1変異で済ませない。** 子は変異によって在ったり無かったりする。
  全変異を見て子の union を取るか、**子を持つ変異を見本にする**
  （#22: `Buttons/L` の見本が `Icon=False, PrependIcon=False, AppendIcon=False`
  だったため、アイコンの寸法がどこにも無く、名前から 36 と当てた。Figma は 32）
- **意味に翻訳しない。** 重なり順は `revZ()` が真偽値のまま返す。
  `counterAxisAlignItems: MAX` を "bottom" と書き写した前例がある

## 検査

| 何を | どこで |
|---|---|
| 単体 component を落としていないか | `tools/impl_coverage_check.py`（`$meta.declared.singleComponents` の宣言を要求） |
| 参照してよいページか | `tools/page_scope_check.py` |
| 器が保存され指紋が一致するか | `tools/exporter_check.py` |
| **画面が全部書き出されているか**（記録層を消せる前提） | `tools/screen_export_check.py` |

## 実害の記録

- **2026-09-02**: FlashEnglish / 414 の器が `COMPONENT_SET` しか集めておらず、
  単体4件（Header / Footer / BottomNavigation / EmptyStates）が書き出しに
  入っていなかった。条件7 の分母が4件小さいまま、どの検査からも見えなかった
- **2026-09-02**: 414 の Figma で `Lists/Subtle` が `Lists` に改名され、同名が
  2つになった。器も鮮度検査も止まった（**止まるのが正しい**。黙って上書きすると
  26件のうち1件が別物にすり替わったまま下流の照合が全部通る）
