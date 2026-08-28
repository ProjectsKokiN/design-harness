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
| `engine/design_check.py` | 禁止パターン検査エンジン（5案件の機能を統合した正本） |
| `shims/design_check_shim.py` | 案件側に置く薄い入口のテンプレート |
| `tools/staleness_check.py` | 下流が上流より古くないか（鮮度差） |
| `tools/figma_freshness.py` | 書き出しが Figma より古くないか（指紋） |
| `tools/sync_pending.py` | 検査未着手の宣言＋ラチェット（増えたら落ちる） |
| `tools/harness_stats.py` | 発火ログの集計（仕組改善層） |
| `tools/contact_sheet.py` | golden を1枚のタイルに |
| `tools/token_query.py` | 値からトークン名の逆引き |
| `vocab/_vocab.json` | status / blockedBy / origin の語彙の正本 |
| `attack/engine_attack_test.py` | エンジンの妨害テスト（全機能に「落ちるケース」を持つ） |
| `ci/` | 各リポジトリへ配る workflow の雛形 |

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
