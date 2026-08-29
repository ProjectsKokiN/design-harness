# design-harness

**デザインハーネスの検査エンジンと道具の正本。** 全プロジェクト共通の仕組みは
ここに1本だけ置き、各プロジェクトには薄いシムと案件固有の記録だけを置く。

2026-08-28 に新設。それまで `design_check.py` は5案件に複製され、テンプレとの
差分が最大515行まで乖離していた（planttalk が `ignore_for_file` に対応しても
他の4本には届かない、という状態）。仕組みのアップデートを全プロジェクトへ
届けるため、置き場を上層に一本化した。

## 構成

| 場所 | 中身 |
|---|---|
| **`DESIGN.md`** | **全案件共通のデザイン憲法**（原則・品質フロア・検証の4段・語彙）。案件側はこれを参照し、写さない |
| `engine/design_check.py` | 禁止パターン検査エンジン（5案件の機能を統合した正本） |
| `shims/design_check_shim.py` | 案件側に置く薄い入口のテンプレート |
| `tools/design_md_check.py` | 案件の DESIGN.md が共通の憲法を参照しているか・写していないか |
| **`rules/<stack>.json`** | **A層: スタック共通の禁止ルール**（生値の直書き。DS の値に依存しない） |
| **`tools/gen_rules.py`** | **B層の生成器**: 段の値が入るルールを tokens.json から作る（`--check` でズレを検出） |
| **`tools/seed_check.py`** | **種まき欠陥テスト**: ルールが実際に発火するか（ラチェットは対象数、これは発火件数） |
| **`seeds/<stack>/`** | 種のひな形（わざと違反させたコード）。案件の `design/seeds/` へコピーする |
| **`tools/gap_report.py`** | **検査が見なかったものを機械が出す**（完了レポートの「限界」を自己申告にしない） |
| `tools/staleness_check.py` | 下流が上流より古くないか（鮮度差） |
| `tools/figma_freshness.py` | 書き出しが Figma より古くないか（指紋） |
| `tools/gen_input_check.py` | 生成器・照合の入力が書き出しだけか（記録層の廃止・2026-08-29） |
| `tools/coverage_check.py` | 照合体制（条件2）: 照合相手が書き出しだけか |
| `tools/sync_pending.py` | 【廃止予定】記録層とともに削除する（既存案件の移行後） |
| `ci/verify.sh.template` | 統合検査の入口の雛形（必須段を減らさない） |
| `tools/harness_stats.py` | 発火ログの集計（任意の道具。2026-08-29 に「仕組改善層」としては廃止） |
| `tools/contact_sheet.py` | golden を1枚のタイルに |
| `tools/token_query.py` | 値からトークン名の逆引き |
| `vocab/_vocab.json` | status / blockedBy / origin の語彙の正本 |
| `attack/engine_attack_test.py` | エンジンの妨害テスト（全機能に「落ちるケース」を持つ） |
| `ci/` | 各リポジトリへ配る workflow の雛形 |

## 憲法の分担（2026-08-29）

デザインの設計基準は**共通＋案件の変数**に分けます。検査エンジンを一本化したのと
同じ理由です——共通部分を各案件の DESIGN.md に手で写していたため、共通側を直しても
届きませんでした（flash-compose は156行のうち案件固有が4節だけ）。

| | 場所 | 中身 |
|---|---|---|
| 共通 | このリポジトリの `DESIGN.md` | 原則6つ・品質フロア（スタック別）・検証の4段・止まったときの区分・完了レポートの書式・モデルの使い分け |
| 案件 | `<案件>/DESIGN.md`（20〜40行） | 使うデザインシステム / スタック / 検証フェーズ / 承認済みの例外 / この案件だけの決まり |

案件側が共通の内容を写すと `tools/design_md_check.py` が落ちます。
案件側に必要な見出しは共通 `DESIGN.md` の ```required-sections``` 宣言が分母です。

## ルールの4層（2026-08-29）

`no-offscale-radius` の正規表現に角丸のスケールが**手で書き写されていた**。
Figma で段を変えた瞬間に静かに古くなる、という「手で写した層」だったので、
記録層・DESIGN.md と同じ処方（生成して、ズレを機械で見る）を当てた。

| 層 | 置き場 | 中身 | 誰が書くか |
|---|---|---|---|
| **A** | `design-harness/rules/<stack>.json` | 生値の直書き禁止。DS の値に依存しない | 手（ここ） |
| **B** | `<DS>/rules/<stack>.generated.json` | 段の値（角丸・ウェイトのスケール） | **`gen_rules.py` が生成** |
| **C** | `<DS>/rules/<stack>.json` | セマンティックの用途規約（`scope-*`）。DS の命名に依存 | 手（DS） |
| **D** | `<案件>/design/rules.json` | その案件だけの禁止 | 手（案件） |

engine の `extends` で D→C→B→A とたどる（**2026-08-29 に再帰化**。それまで1段しか
読まず、A層が黙って落ちていた）。

## 「検査が働いているか」を見る3つ

| 道具 | 数えるもの | 捕まえる失敗 |
|---|---|---|
| `attack/engine_attack_test.py` | エンジンの挙動 | エンジンが壊れた |
| `expected_targets`（engine） | 読んだファイル数 | 検査対象が黙って狭まった |
| `tools/seed_check.py` | **ルールごとの発火件数** | **ルールが黙って死んだ** |

`tools/gap_report.py` はこの3つの結果を合わせて「見なかったもの」を出す。
発火0のルールは、**種があれば「コードが綺麗」・無ければ「効いているか不明」**と
区別して報告する。

## 各プロジェクトへの導入

```bash
cd <プロジェクト>
git submodule add https://github.com/ProjectsKokiN/design-harness design/harness
cp design/harness/shims/design_check_shim.py design/design_check.py
# rules.json は従来どおり design/rules.json（互換）
```

hook・verify.sh・CI は従来どおり `design/design_check.py` を呼べばよい。
シムがエンジンへ委譲する。案件固有の判定（Figma に画面が無い対象の soften、
層の注意）はシムの `HOOKS` に書く。

エンジンの更新を取り込むには:

```bash
git -C design/harness pull origin main
```

## self-test を持たない道具（意図的な例外）

「検査が働いているか」を見るのがこのリポジトリの主眼なので、**判定を出す道具は
必ず落ちるケースを持つ**。持たないものは、理由を明記した例外だけ。

| 道具 | 理由 |
|---|---|
| `pin_check` | ネットワークが要る（本人が冒頭に明記） |
| `figma_freshness` | 同上。Figma 本体を叩く |
| `contact_sheet` / `token_query` / `harness_stats` | **合否を出さない**（人が見る道具） |
| `sync_pending` | 廃止予定（記録層とともに削除する） |

## 変えるときの決まり

- **エンジンを変えたら `python3 attack/engine_attack_test.py` を先に通す。**
  新機能には「落ちるケース」を必ず1つ足す（通ることの確認だけでは、
  何も見ていない可能性を排除できない）
- 案件で生まれた検査・語彙・治具は、ここへの回収を提案する
  （`mobile-implement-ui` の `references/feedback-rules.md`）
- 検査は対象を書き換えない（aub の verify.py の教訓: 上書きしてから比較すると
  同じコマンドが2つの答えを返す）

## 関係する正本

- ハーネスの手順・テンプレート: `~/.claude/skills/mobile-harness-setup/`
- 本番リリースの合格条件: 同 `references/production-gate.md`
- Web の参照実装: `qnd-database/site/design/harness/`
