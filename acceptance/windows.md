# Windows 受け入れテスト（2026-08-28・第1回）

環境: Windows 11 / Python 3.14.3（`python3` コマンドは無し、`python` のみ）/ Git Bash

## 手順1: 取得

```
git clone https://github.com/ProjectsKokiN/design-harness
cd design-harness
```
成功。README.md も読めた。

## 手順2: エンジン自身の妨害テスト

コマンド: `python attack/engine_attack_test.py`

- 素のコマンドでは出力が文字化けした（cp932 環境で日本語が化ける。過去の
  qnd-database の不具合と同じ症状）。終了コード自体は 0 で問題なし。
- `PYTHONUTF8=1` を付けて再実行すると正しく表示された。

```
妨害テスト: 24 件 通過 / 0 件 失敗
```
終了コード: 0

**判断した点（ドキュメントに書かれていない）**: `PYTHONUTF8=1` を毎回付ける
必要があるという前提は prompts.md に明記されていない。cp932 環境では
必須と考えて以降すべてのコマンドに付けた。

## 手順3: 合成プロジェクトで仕込みが落ちるか

`/c/tmp/claude/design-harness-synth` に `.git`（空）・`design/rules.json`・
`lib/bad.dart`・`lib/good.dart` を作成。

**詰まったところ**: 最初、bash の `cat > file <<'EOF'` で rules.json を書いたところ、
JSON 中の `\\(`（バックスラッシュのエスケープ）が `\(` に化けて壊れた
（ヒアドキュメント経由でバックスラッシュが1本失われた）。結果、
`design_check.py` が「rules.json が読めません」で exit 2 になり、
検査が動く前の設定ミスで落ちていた。Write ツールで書き直して解決。
**これは design-harness 側の不具合ではなく、こちらの投入手順の問題**。

修正後:
```
python <design-harness>/engine/design_check.py --rules design/rules.json --all
```
出力:
```
デザインハーネス違反を検出しました。代替案に従って修正してください。
- [no-raw-color] lib\bad.dart 行1
    禁止: 生の色
    代替: Sem.* を使う
    該当: final c = Color(0xFFFF5800);

（中身を読んだ 2 ファイル / 対象外 3 ファイル）
```
終了コード: 2（期待どおり）

## 手順4: bad.dart を消して再実行

出力:
```
デザインハーネス: 1 ファイルを 1 ルールで検査。違反なし。（対象外 4 ファイル / warn 0 件）
```
終了コード: 0（期待どおり）

## 手順5: 空振りの検知

`file_extensions` を `[".nothing"]` に変更して実行。
出力:
```
デザインハーネス異常: 中身を読んだファイルが 0 です。走査が空振りしています（対象外 5 件）。file_extensions と project_root を確認してください。
```
終了コード: 2（期待どおり。exit 0 で「違反なし」にはならなかった）

`file_extensions` を `[".dart"]` に戻して確認終了。

## 手順6: Git Bash から `/c/...` 絶対パス

`--rules /c/tmp/claude/design-harness-synth/design/rules.json` を Git Bash から
指定して実行。

- bad.dart 無し: `1 ファイルを1ルールで検査。違反なし。（対象外4件）` 終了コード 0
- bad.dart を戻して再実行: 手順3と同じ違反検出（`中身を読んだ 2 ファイル / 対象外 4 ファイル`）
  終了コード 2

**過去の「97ファイル素通り」（絶対パスが解決できずファイル数0で緑）は再現しなかった。**
読んだファイル数が毎回一致しており、`/c/...` パスは正しく解決されている。

## 手順7: 日本語表示

`PYTHONUTF8=1` を付けた状態では「デザインハーネス」「違反」「中身を読んだ」は
すべて正しく表示された。付けない場合（手順2の最初の実行）は文字化けした
（内容は判読できないが、終了コードは正常だった＝処理自体は壊れていない、
表示だけの問題）。

## 手順8: 鮮度差の検査

`~/dev/design-systems` は本セッションの直前作業（flash-compose のマージ検証）で
既にクローン済みだった。`git pull origin main` で最新化してから実行。

正常時:
```
OK: 414/components/components.json（... 遅れ 0 日 ...）
OK: 414/tokens/tokens.json（... 遅れ 0 日 ...）
OK: 414/FLUTTER_GAPS.md（... 遅れ 0 日 ...）

3 対すべて鮮度に問題ありません。
```
終了コード: 0（期待どおり）

`414/tokens/tokens.json` の `$meta.syncedAt` を `2026-01-01` に書き換えて再実行:
```
1 件の下流が上流より古くなっています。取り直すか、意図した保留なら $meta に日付と理由を書いてください。
OK: 414/components/components.json（...）
NG: 414/tokens/tokens.json（下流 2026-01-01 / 上流 ... 遅れ 233 日 ...）
OK: 414/FLUTTER_GAPS.md（...）
```
終了コード: 1（期待どおり）。確認後 `2026-08-22` に書き戻し、`git status` で
差分が残っていないことを確認した。

git のサブプロセス呼び出し・日付比較はどちらも Windows で正常に動作した。

## 手順9: 既存3案件での実行

`~/dev` に flash-compose / aub-familywalk / planttalk のクローンあり。

- **aub-familywalk**: `design/design_check.py` が存在しない（`find` で該当0件）。
  スキップした。
- **flash-compose**: `design/design_check.py`（351行、独自コピー）を実行。
  ```
  デザインハーネス注意: ルール no-raw-zero-spacing の paths のうち
  ['lib/theme', 'lib/catalog'] は exclude_paths に潰されて走りません
  （実際に走るのは ['lib/ui']）
  デザインハーネス検査: 対象 63 件・読めた 63 件
  ```
  終了コード: 0
- **planttalk**: `design/design_check.py`（186行、独自コピー）を実行。
  **出力なし**、終了コード 0。スクリプトの docstring に「違反ゼロなら
  何も出力せず exit 0（追加コストなし）」とあり、仕様どおりの沈黙成功。
  ただし「0件検査して0件」なのか「全部読んで0件」なのかが標準出力からは
  区別できない（空振りでも同じ画面になる）。今回は `--all` 実行前に
  ファイル数を確認していないため、**空振りでないことは検証できていない**。

**ドキュメントとの食い違い（重要）**: prompts.md は「3案件とも submodule
導入済みです」としているが、実際にはどの案件にも `.gitmodules` が無く、
`design/harness/` サブモジュールも存在しない。3案件は今も
「design_check.py が案件ごとにコピーされ、内容が食い違っている」という、
まさに README が解消したいと書いている状態のまま。flash-compose（351行）と
planttalk（186行）は行数からして明らかに別物で、統合エンジンへの移行は
まだこの3案件に届いていない。

## 詰まったところ（まとめ）

- 素の `python` 実行では日本語が化ける（cp932）。`PYTHONUTF8=1` が必須という
  前提が prompts.md に明記されていない
- bash のヒアドキュメント（`<<'EOF'`）で JSON 中の `\\` が壊れる場合がある。
  今回は Write ツールで書き直して回避したが、手順3の JSON をそのままシェルに
  貼る運用だと同じ事故が起きうる
- 手順9の3案件は、ドキュメントが前提とする「submodule 導入済み」状態に
  なっておらず、実行できたのは「案件ごとに複製された旧スクリプト」の方だった
- planttalk の実行結果（出力なし・exit 0）が「正常に0件」なのか「空振り」なのか、
  今回の実行手順だけでは確認できなかった（意図的な仕様どおりの沈黙と、
  空振りの沈黙が外形的に区別できない）

## python / python3、パス区切り、文字コード、改行コードで引っかかった点

- `python3` は無し。`python` に読み替えた（Python 3.14.3）
- パス区切り: Git Bash からの `/c/...` は engine 側で問題なく解決された
  （過去の97ファイル素通りは再現せず）
- 文字コード: cp932 環境では `PYTHONUTF8=1` が無いと出力が化ける
- 改行コード: 今回の範囲では問題を確認しなかった
