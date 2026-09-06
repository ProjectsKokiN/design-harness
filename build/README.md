# build — ビルドの仕組み（iOS と Android の共有の置き場）

**この階層は iOS 専用でも Android 専用でもありません。** どちらの機体からも参照します。
iOS 固有・Android 固有の名前をここに付けないでください。

## いま何をしているか（2026-09-06 開始）

**Mac mini（iOS）と Windows（Android）が、別々にビルドの実態を書き出しています。**
両方が揃ってから、統合できるものと機体で分けるものを決めます。

| 段 | 誰が | 何を | 状態 |
|---|---|---|---|
| 1. 棚卸し | Mac mini | `analysis/build-ios-<日付>.md` + `.json` | 進行中 |
| 1. 棚卸し | Windows | `analysis/build-android-<日付>.md` + `.json` | 進行中 |
| 2. 突き合わせ | Mac mini | 2つの `.json` を `依存` の列で機械的に仕分ける | 1 の両方が揃ってから |
| 3. 分割 | 両方 | 統合分をここへ・機体分を各スキルへ・案件の値を `<案件>/design/` へ | 2 のあと |

**2 より先に 3 をやらないでください。** 片方の形に合わせにいくと、統合の判定が
「先に書いたほうが正しい」になります。

## 項目表

`inventory-schema.json` が唯一の正です。**両機体が同じ列で書く**ためにあります。

```
python3 build/inventory_check.py analysis/build-android-2026-09-06.json
python3 build/inventory_check.py --self-test
```

**統合の可否は各機体が判定しません。** 各行の `依存` を事実として書くだけです。
判定は 2 の段で規則を機械的に当てます。

| `依存` | 行き先 |
|---|---|
| `none` | ここ（`build/`）に統合 |
| `env` / `credential` / `hardware` | 機体のスキルへ |
| `project` | `<案件>/design/<platform>.json` へ |

## なぜ `.json` も要るか

2026-09-06 の機体分析（78件）は `.md` と `.json` の対で出したので、項目単位で
突き合わせられました。**散文だけだと読み手が解釈し直すことになり、統合の判定が
人の印象になります。**
