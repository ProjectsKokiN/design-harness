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

## 検査

| 何を | どこで |
|---|---|
| 単体 component を落としていないか | `tools/impl_coverage_check.py`（`$meta.declared.singleComponents` の宣言を要求） |
| 参照してよいページか | `tools/page_scope_check.py` |
| 器が保存され指紋が一致するか | `tools/exporter_check.py` |

## 実害の記録

- **2026-09-02**: flash-compose / 414 の器が `COMPONENT_SET` しか集めておらず、
  単体4件（Header / Footer / BottomNavigation / EmptyStates）が書き出しに
  入っていなかった。条件7 の分母が4件小さいまま、どの検査からも見えなかった
- **2026-09-02**: 414 の Figma で `Lists/Subtle` が `Lists` に改名され、同名が
  2つになった。器も鮮度検査も止まった（**止まるのが正しい**。黙って上書きすると
  26件のうち1件が別物にすり替わったまま下流の照合が全部通る）
