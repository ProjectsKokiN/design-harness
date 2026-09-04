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
| **`tools/gen_gate.py`** | **関門の合格条件の生成器**: `production-gate.md`（正本）から`gate/conditions.json` を作る（`--check` でズレを検出）。**条件が何件かを機械で持つ** |
| **`tools/seed_check.py`** | **種まき欠陥テスト**: ルールが実際に発火するか（ラチェットは対象数、これは発火件数） |
| **`tools/gen_notcaptured.py`** | **書き出しが読まなかったプロパティ**を一覧との差分から生成する。`gen_io.absent()` で問える |
| **`tools/shared_check.py`** | **「自分の機体だけ緑」を止める**: 既定ブランチとの衝突（CI が起動しない）／レジストリが枝に居る／受信箱が枝に取り残される／説明の裏取り |
| **`tools/impl_value_check.py`** | **実装の中だけの数値**を見つける（書き出しにも生成物にも出どころが無い値）。正しく Figma に無いものは理由つきで宣言する |
| **`tools/screen_export_check.py`** | **画面のノード木が全部書き出されているか**（記録層を消せる前提条件）。「在る」と「足りている」を分ける |
| **`tools/hollow_check.py`** | **空振りの検査**: 例外を捨てる・期待値の自己参照・緩い finder・誰も見ていない文字。**検査は回っているのに中身が空**の形を見る |
| **`tools/portable_check.py`** | **Windows でだけ落ちる書き方**（`encoding=` 抜け・素のコマンド名）と、cp932 で全道具を回して死なないか |
| `tools/_utf8.py` | 出力の文字コードで死なないようにする（各道具が import するだけ。単体では回さない） |
| `tools/issue_scan.py` | 前回まとめた日時以降のやりとりを取り出す（`/harness-issues` が使う） |
| **`seeds/<stack>/`** | 種のひな形（わざと違反させたコード）。案件の `design/seeds/` へコピーする |
| **`tools/gen_io.py`** | **生成器の入出力の基盤**（書き出しを読む・件数を照合・生成物を LF で書く・色の変換） |
| **`tools/issue_sync.py`** | **直せていない課題を GitHub の Issue に写す**（`--check` は網なし・`--inbox` は全リポジトリ一覧） |
| **`tools/duplication_check.py`** | **案件をまたぐ複製を見つける**（回収の候補を機械で出す）。設定は `duplication.json` |
| **`tools/gen_verify.py`** | **生成し直して差分が出たら落ちる**（台帳 `generators.json` が唯一の正）。案件ごとの複製を 2026-09-02 に共有化 |
| **`exporters/_preamble.js`** | 書き出し器のひな形（許可リスト・器が数える・同名で止まる） |
| **`tools/figma_names.py`** | **Figma 名 → 識別子の規則の正本**（2026-09-02 に aub から回収）。生成器も検査もここを import する |
| **`tools/machine_scope.py`** | **検査の段を、その失敗を起こせる機体に結び直す**（`--owns` で段を結び、`--check` で担当外の変更を落とす） |
| `templates/machine-scope.json` | 担当の宣言のひな形（案件の `design/` へコピーする） |
| **`tools/gap_report.py`** | **検査が見なかったものを機械が出す**（完了レポートの「限界」を自己申告にしない） |
| **`tools/expectation_source_check.py`** | 照合テストの期待値が書き出し由来か（手書きの期待値を禁じる） |
| **`tools/exporter_check.py`** | 書き出しを作った器が保存され、指紋が一致するか |
| **`tools/tree_test_check.py`** | 条件9 の網羅（状態・スロットを持つセットにテストがあるか） |
| **`tools/stage_check.py`** | **verify.sh の各段が「落ちるところを見た」道具か**（self-test の有無と結果） |
| **`tools/fingerprint_parity.py`** | 指紋が JS と Python で同じ値になるか（非 ASCII の固定具で照合） |
| **`fingerprint/text_digest.{py,mjs}`** | テキスト指紋の正本（両言語）。**案件が自前で書かない** |
| `tools/staleness_check.py` | 下流が上流より古くないか（鮮度差） |
| `tools/impl_coverage_check.py` | **実装網羅（条件7）**: Figma にあるものが全部実装されているか。トークンは完全一致で照合 |
| `tools/check_render_gaps.py` | **再現性の判定（条件5）**: 値が合っても描画で別物になる指定と、判定の網羅 |
| `tools/page_scope_check.py` | 参照してよい Figma ページをフェーズで縛る |
| **`tools/pin_check.py`** | **submodule のピンが上流の既定ブランチから遅れていないか**。枝の途中を指していたら落とす。遅れの中に**この案件が使っている道具の変更**が含まれれば名指しする |
| `tools/ci_path_check.py` | 案内しているパスが実在するか / rules.json の extends が CI から解決できるか（`--rules`） |
| **`tools/readme_check.py`** | **この表がディスクと合っているか**（手で保守する一覧は古くなる） |
| `tools/figma_freshness.py` | 書き出しが Figma より古くないか（指紋） |
| `tools/gen_input_check.py` | 生成器・照合の入力が書き出しだけか（記録層の廃止・2026-08-29） |
| `tools/coverage_check.py` | 照合体制（**参考**。条件2 は 2026-09-03 に廃止）: 照合相手が書き出しだけか |
| `tools/sync_pending.py` | 【廃止予定】記録層とともに削除する（既存案件の移行後） |
| `ci/verify.sh.template` | 統合検査の入口の雛形（必須段を減らさない） |
| `tools/harness_stats.py` | 発火ログの集計（任意の道具。2026-08-29 に「仕組改善層」としては廃止） |
| `tools/contact_sheet.py` | golden を1枚のタイルに |
| `tools/token_query.py` | 値からトークン名の逆引き |
| `vocab/_vocab.json` | status / blockedBy / origin の語彙の正本 |
| `attack/engine_attack_test.py` | エンジンの妨害テスト（全機能に「落ちるケース」を持つ） |
| `tools/stage_check.py --min-coverage N` | **self-test が本体の N% を通ることを求める**（持っているだけでは何も証明していない） |
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

**案件の rules.json が A・B・C を「並べて」継承する。入れ子にしない。**

```json
"extends": [
  "../../design-systems/<DS>/rules/flutter.json",            // C
  "../../design-systems/<DS>/rules/flutter.generated.json",  // B
  "../../design-harness/rules/flutter.json"                  // A
]
```

入れ子（案件 → DS → 共通）にすると、**extends を1段しか読まないエンジンで奥の層が
黙って落ちる**。2026-08-29 に flash-compose で実測: ルールが 12 → 7 に減り、
**それでも「違反なし」で exit 0** だった。submodule のピンが古いだけで起きる。

engine 側も再帰化した（循環検出・深さ上限つき）が、**並列に書くのが正しい**——
古いピンでも新しいエンジンでも同じ結果になるのは並列だけ。
同じ id が複数の層に載っても engine が1件に畳む（子が勝つ・上書きは注意を出す）。

### `expected_rules`（ルール数のラチェット）

```json
"expected_rules": 11
```

読み込めたルール数の下限。**上の 12→7 は `expected_targets`（ファイル数）を
素通りした。** 層が落ちる・パスを綴り間違える・ピンが古い、のどれでも件数が減るので、
数で止める。

### A 層に入れる基準

**生値の直書きを禁じるものだけ。** どの案件でも同じ答えになるものに限る。

- 入れない（建築上の好み）: import の層構造・命名・ファイル分割
  → `rules/<stack>-optional.json`（採用したい案件が extends する）
- 入れない（DS のトークン種に依存）: フォント・モーションのトークンが要るもの
  → その DS の C 層

**実例**: `no-direct-generated-import` を一度 A 層に上げたところ、flash-compose で
8件の違反が出た。aub の設計判断であって、flash-compose は意図的に逆の作りだった。

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

## 「同じことを2か所に書かない」の適用先

| 何 | 正本 | 回収した日 |
|---|---|---|
| 検査エンジン | `engine/design_check.py` | 2026-08-28（5案件の複製・最大515行乖離） |
| デザインの憲法 | `DESIGN.md` | 2026-08-29（案件の DESIGN.md に手写し） |
| 段の値が入るルール | `tools/gen_rules.py` の生成物 | 2026-08-30（正規表現に手写し） |
| 関門の合格条件 | `tools/gen_gate.py` の生成物 | 2026-09-04（正本が ~/.claude にあり CI から読めない） |
| **識別子の規則** | **`tools/gen_io.py`** | **生成器の入出力の基盤**（書き出しを読む・件数を照合・生成物を LF で書く・色の変換） |
| **`tools/issue_sync.py`** | **直せていない課題を GitHub の Issue に写す**（`--check` は網なし・`--inbox` は全リポジトリ一覧） |
| **`tools/duplication_check.py`** | **案件をまたぐ複製を見つける**（回収の候補を機械で出す）。設定は `duplication.json` |
| **`tools/gen_verify.py`** | **生成し直して差分が出たら落ちる**（台帳 `generators.json` が唯一の正）。案件ごとの複製を 2026-09-02 に共有化 |
| **`exporters/_preamble.js`** | 書き出し器のひな形（許可リスト・器が数える・同名で止まる） |
| **`tools/figma_names.py`** | **2026-09-02**（`impl_coverage_check` が別実装を持ち、文書の「唯一の正」と食い違っていた） |

## 課題の流れ（2026-09-02 に決めた運用）

```
案件がハーネスで開発する
  → 課題が見つかる
  → 宣言する（allow / $warn_only / entries に why と期限）
  → issue_sync が Issue に写す（--apply）
  → **定期的に共有層のセッションがまとめて解く**（--inbox で一覧）
  → 直したら宣言を消す → Issue が閉じる（--apply）
```

| やること | コマンド |
|---|---|
| 溜まった課題を見る | `issue_sync.py --inbox` |
| 宣言を Issue に写す | `issue_sync.py --apply --root <案件>` |
| Issue の無い課題を知らせる（CI） | `issue_sync.py --check --root .` |
| 宣言する場所が無い課題を立てる | `issue_sync.py --new --title … --why … --closes-when …` |

**課題と「期限つきの決定」は期限で分けます。** 期限が遠い宣言は「いまは決着している」、
30日以内に近づいたら「やること」。手で印を付けないので、印の付け忘れが起きません。
実測（2026-09-02）: 宣言67件のうち、いま課題とするものは7件。

**Issue を立てる先は `blockedBy` で決まります。** 案件で見つかっても直す場所が
共有層なら、Issue は共有層に立ちます（`blockedBy: design-harness`）。
立てた URL は宣言に書き戻すので、同じ課題が二重に立ちません。

## self-test を持たない道具（意図的な例外）

「検査が働いているか」を見るのがこのリポジトリの主眼なので、**判定を出す道具は
必ず落ちるケースを持つ**。持たないものは、理由を明記した例外だけ。

| 道具 | 理由 |
|---|---|
| `pin_check` | ネットワークが要る（本人が冒頭に明記） |
| `figma_freshness` | 同上。Figma 本体を叩く |
| `contact_sheet` / `token_query` / `harness_stats` | **合否を出さない**（人が見る道具） |
| `sync_pending` | 廃止予定（記録層とともに削除する） |

`design/design_check.py`（案件のシム → エンジン）は `--self-test` を持たないが、
**`attack/engine_attack_test.py` の39件がその役目**を果たす。`stage_check` からは
「外部の道具」として一覧に出る。

## 変えるときの決まり

- **段を足す前に、その道具が落ちるところを見る。** `--self-test` に落ちるケースを
  書き、`stage_check.py` が通ることを確かめる。文章の決まりでは守れなかった
  （aub 2026-08-29: 何も見ていない検査が緑で並び、1日に2回踏んだ）
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
