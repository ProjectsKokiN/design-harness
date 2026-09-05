# 受け入れテストのプロンプト

そのまま貼って使う。実施したら `acceptance/<マシン名>.md` に記録を書き、コミットして push する。

---

## Windows（2026-08-28・第1回）——【実施済み。記録は windows.md】

実施の結果、エンジン側を直した: 日本語出力は PYTHONUTF8 なしで化けないよう
stdout/stderr を UTF-8 に reconfigure する形に変更（エンジンが対処するので、
このプロンプトの手順に PYTHONUTF8 の前提は要らなくなった）。
手順3の JSON はヒアドキュメント経由だと `\\` が壊れることがある——
ファイルに書くときはエディタ（Write 系ツール）で書くこと。

```
design-harness の受け入れテストをお願いします。あなたは Windows 機で、
この仕組みを作っていない側です。テストされているのはあなたではなく、
ドキュメントと仕組みです。

## 背景

デザインハーネスの検査エンジンを、5案件に複製されていた状態から1本に統合しました
（2026-08-28）。統合したエンジンには、過去に Windows で見つかった不具合への
対策コードが入っています。**ただし macOS でしか検証していません。**

過去に Windows で見つかった重い不具合（qnd-database・2026-08-25）:
- 日本語の文字列で成否を判定していて、cp932 環境では違反0でも失敗した
- 絶対パスを渡しており、Git Bash の /c/... を Windows の Python が解決できず
  97ファイル全部が素通りした。それでも「OK」と表示された

同じ形の穴が新しいエンジンに残っていないかを確かめてください。

## 手順

1. リポジトリを取得します（public です）。

       git clone https://github.com/ProjectsKokiN/design-harness
       cd design-harness
       type README.md

2. **エンジン自身の妨害テスト**を走らせます。24件あり、全部が
   「落ちるべきものが落ちるか」を見ています。

       python attack\engine_attack_test.py

   python が無い / python3 でないと動かない場合は、**その事実を記録してください**
   （ドキュメントが python3 前提で書かれているなら、それがこのテストの成果です）。

3. **合成プロジェクトで、仕込みが落ちることを確かめます。**
   一時ディレクトリに次を作ってください。

   - `.git` という空ディレクトリ（プロジェクトの起点の目印）
   - `design\rules.json`:

         {"version":1,"file_extensions":[".dart"],"exclude_paths":[],
          "rules":[{"id":"no-raw-color","severity":"error",
                    "pattern":"Color\\(0x[0-9A-Fa-f]{8}\\)",
                    "forbidden":"生の色","instead":"Sem.* を使う"}]}

   - `lib\bad.dart`: `final c = Color(0xFFFF5800);`
   - `lib\good.dart`: `final c = Sem.accent;`

   そのディレクトリで次を走らせ、**終了コードを必ず確認**してください。

       python <design-harness>\engine\design_check.py --rules design\rules.json --all
       echo %ERRORLEVEL%      (cmd)   /   $LASTEXITCODE   (PowerShell)

   期待: **exit 2**。出力に no-raw-color と「中身を読んだ N ファイル」が出ること。

4. `lib\bad.dart` を消して、もう一度走らせます。
   期待: **exit 0**。「違反なし」と、読んだファイル数が出ること。

5. **空振りの検知**を確かめます。`rules.json` の `file_extensions` を
   `[".nothing"]` に変えて走らせます。
   期待: **exit 2** で「空振り」と出ること。**exit 0 で「違反なし」と出たら
   それが不具合です**（1ファイルも読んでいないのに緑）。

6. **Git Bash から**（cmd/PowerShell ではなく）同じことを試してください。
   過去の97ファイル素通りは Git Bash の /c/... パスが原因でした。

       # Git Bash で
       python engine/design_check.py --rules /c/.../design/rules.json --all

7. **日本語が化けないか**を見てください。出力の「デザインハーネス」「違反」
   「中身を読んだ」が読めるか。化けたら、その画面をそのまま記録してください。

8. 鮮度差の検査も走らせます（git のサブプロセスを使います）。

       git clone https://github.com/ProjectsKokiN/design-systems
       python design-harness\tools\staleness_check.py --config design-systems\staleness.json

   期待: **exit 0** で「3 対すべて鮮度に問題ありません」と出ること。
   見るのは、git のサブプロセスと日付の読み取りが Windows で動くかです。

   **落ちることも確かめてください。** `design-systems/414/tokens/tokens.json` の
   `$meta.syncedAt` を古い日付（例 `2026-01-01`）に書き換えて走らせ、
   **exit 1** で「遅れ」が出ることを見てください。確認したら書き戻します。

9. 手元に FlashEnglish / aub-familywalk / planttalk のクローンがあれば、
   そこでも `python design/design_check.py --all` を走らせてください
   （3案件とも submodule 導入済みです）。無ければ飛ばして構いません。

## 記録してほしいこと

`acceptance/windows.md` に書いて、コミットして push してください。

- 各手順の**終了コードと出力**（「動きました」ではなく、実際の数字）
- **詰まったところ**。推測で乗り切らず、詰まったまま書いてください
- ドキュメントに書かれていなくて自分で判断した箇所（＝ドキュメントの穴）
- python / python3、パス区切り、文字コード、改行コードで引っかかった点

**「動きました」だけの報告は受け取れません。** 手順3と5で**落ちること**を
確認できていなければ、検査が動いている証拠になりません。

## 環境について

- python3 が無い環境なら python に読み替えて構いません。**その読み替えが
  必要だったこと自体を記録してください**（テンプレートを直す材料になります）
- 何かをインストールする必要が出たら、インストールせずに**その旨を記録**して
  ください。前提が増えているということなので、それも成果です
```

---

## 記録の書き方（例）

```markdown
# Windows 受け入れテスト（2026-08-28）

環境: Windows 11 / Python 3.12.1 / Git Bash

## 手順2: 妨害テスト
コマンド: python attack\engine_attack_test.py
結果: 妨害テスト: 24 件 通過 / 0 件 失敗
終了コード: 0

## 手順3: 仕込みが落ちるか
終了コード: 2（期待どおり）
出力: （そのまま貼る）

## 詰まったところ
- README に `python3` と書かれているが、この環境では `python` でないと動かない
- ...
```
