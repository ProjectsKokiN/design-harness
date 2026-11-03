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
| `export_components.js` | **部品の各変異の中身**（行の形は `export_frames.js` と同じ）。深さ 0 の行が変異の寸法。頭に `_preamble.js` を貼って回す（#145・2026-09-25） |

`export_frames.js` の決まり:

- 部品のインスタンスは `instanceOf`（セット名とバリアント）まで。**中には降りない**
- 色・文字スタイル・効果は**変数／スタイルの名前**で書く。**解決しない**
  （`counterAxisAlignItems: MAX` を `"bottom"` と書き写すような翻訳を挟むと、
  **それが「正」になる**）
- **同じ形の兄弟は畳む**（ビンゴの 5x5 は 25 行ではなく 1 行 + 位置の列）
- **文字はスタイル名（`ts=`）と実際の書体（`font=書体/太さ/大きさ`）の両方を書く**
  （#145。スタイル名だけだと、スタイルの中身が変わったことに行から気づけない）
- **塗りを潰さない**（#149）。変数の名前だけで書くのは、塗りが 1 つで単色のときだけ。
  グラデーションは止め色を `変数名か#hex@位置` で `>` につなぐ。塗りのスタイルは `fillStyle=`、
  角ごとに違う角丸は `radius=左上,右上,右下,左下`
- **インスタンスは中へ降りないが、性質の値（`props=`）と中の上書き（`ov=`）は書く**（#150・#152）。
  引けない上書きは戻しの `$meta.読めなかったもの` に並ぶので、pack で `notcaptured.json` の
  「読めなかったもの」へ写す
- **戻しが失われる形は 2 つあり、見分けられる**（#148）。文字に U+2028 などの区切り文字が入ると
  転送が行の途中で切れて**丸ごと失われる**（大きさに関係なく、その画面は何度回しても落ちる）。
  器は返す直前に JSON の書き方で逃がす（`safe()`）。20KB を超えたときは `// truncated to 20kb` が
  付いて**切り詰めて返る**（別の失敗。ONLY_IDS や ONLY で分ける）

`export_components.js` の決まり:

- **全部の変異を出す**（見本を 1 変異で済ませない。#22）。大きいセットは
  `VARIANT_SLICE` で区切り、`variantTotal` と突き合わせて足りているかを数で確かめる
- `hex` から `walk` までは `export_frames.js` の写し。**片方だけ直すと
  `attack/preamble_test.mjs` が落ちる**

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
| 器が保存されハッシュが一致するか | `tools/exporter_check.py` |
| **画面が全部書き出されているか**（記録層を消せる前提） | `tools/screen_export_check.py` |

## 実害の記録

- **2026-09-02**: FlashEnglish / 414 の器が `COMPONENT_SET` しか集めておらず、
  単体4件（Header / Footer / BottomNavigation / EmptyStates）が書き出しに
  入っていなかった。条件7 の分母が4件小さいまま、どの検査からも見えなかった
- **2026-09-02**: 414 の Figma で `Lists/Subtle` が `Lists` に改名され、同名が
  2つになった。器も鮮度検査も止まった（**止まるのが正しい**。黙って上書きすると
  26件のうち1件が別物にすり替わったまま下流の照合が全部通る）

## 大きい画面は REST で取る（#179・2026-11-03）

`export_frames.js` は use_figma の1回の戻り（約18KB）に収まる量しか返せない。画面が大きく、分割（`frame_io.py`）でも
書き写す量が現実的でないときは、`tools/export_frames_rest.py` で **REST API から同じ行の形**を作ってファイルへ直接書く。

- 変数は REST では id しか返らないので、`export_variables.js` の出力（2026-11-03 から `id`・`key`・全モードの値を書く）を `--variables` に渡す
- 同じ行になるかは、器に行ごとのハッシュだけを返させ（`TRANSFER_MODE = 'manifest'`）、`--compare-hashes` で照合する
- portfolio の 23 画面（964 行）で 960 行が一致。残り 4 行は REST では区別できない違い（部品の上書きで、効果のスタイルだけか中身もか）
- 両方の器で、部品の性質（props）は**名前の順**に並べる（Plugin API の返す順に決まりが無く、REST と合わせられないため）

## 子のノード ID は行の外の `ids` に入る（#157・2026-11-03）

`export_frames.js` と `export_frames_rest.py` は、画面ごとに `rows` と同じ順・同じ数の `ids` を書きます。
畳んだ行（`名前×N`）は ID の配列です。**行とその行のハッシュは変わりません**（ID は行の外にあるため）。

- 分割で取るとき: manifest は `idsHash`、rows は行と同じ番号の `ids` を返し、`tools/frame_io.py` が組み立てて照合する。
  `--previous` で使い回した行のノードが作り直されていると、ID の一覧のハッシュが合わずに止まる（全部の行を取り直す）
- `idsHash` の無い manifest は古い器で、`ids` を持たない
- 決めた経緯: ユーザーの選択（原文）「行の外に ID の一覧を足す」。行の中に `id=` を足すと同じ形の兄弟を畳めなくなり、
  全案件で行のハッシュが変わる。名前の並びで引くと、同じ名前の兄弟（FlashEnglish の ButtonsGroup 2つ）を取り違える
