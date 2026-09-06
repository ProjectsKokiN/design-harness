# Windows の開発の仕組みの実態（2026-09-06）

実施デバイス: **Windows (Dev-Logic)** / Python 3.14.3 / Git Bash
突き合わせ相手: Mac mini 側の分析（統合した事例 79 件）
対象: Flutter 2案件（FlashEnglish=`~/dev/flash-compose` / aub-familywalk）

この文書は 2026-09-05〜09-06 に Windows 機で行った分析を、**Mac mini と同じ軸で数え直した**ものです。
第1部は元の分析をそのまま載せ、第2部で Mac mini の軸に変換しています。新しい調査はしていません
（記載場所の `none` 判定に必要な grep だけ追加で実行しました）。

---

# 第1部: 元の分析（要約せず、そのまま）

## 方法

並列調査8領域（design-harness の PLAN/DESIGN/POST-PUSH/README・道具群・attack/acceptance・
flash の Windows 層・aub の Windows 層・スキル群・memory・Issue）
→ 設計3案を独立に作成（既存優先 / 新案件優先 / 失敗から逆算）
→ 3観点で審査（既存整合 / 再発防止 / 実行可能性）
→ 1本に統合 → 統合案が依拠する主張6件を反証

審査は3人とも「**失敗から逆算**」を最良に選びました（8/10・8/10・8/10）。
反証は**6件すべてが耐えました**（崩れた主張は0件）。

## 統合案の中心主張

> Windows 開発層の器は design-harness にほぼ揃っている。足りないのは (a) 配線（flash は verify.sh が
> step 形式でなく段を拾えない・portable_check が design/gen に向いていない、aub は core.hooksPath
> 未設定でフックが眠っている）、(b) 無言で緑になる穴（眠ったフックが stage_check を素通りする・
> 変異試験が基準 self-test の落ちる道具を分母から外す・portable_check が docstring の4項目のうち
> 3項目しか実装していない）、(c) 依頼の決まりが配布・報告の型まで書き切られていないこと、の3つ。
> したがって仕事は「共有層の穴を実装で塞ぐ」「案件の配線を直す」「依頼の決まりを書き切る」
> 「新案件に器が入る工程を足す」に閉じ、新しい運用道具（ビルド・配布の入口）と新スキルは作らない。

前提の訂正（実測）: **aub の取り込み遅れは MacBook Air の仕事ではない。** origin/main のピン 99a98c7 は
design-harness main から2遅れで inbox_tool / shared_check / swallow_check / situations_check の4本とも
既に入っている。71 遅れはユーザーが管理する作業ブランチ c329bc3 の話で、直しは Windows 側の pull。
flash のピン 59 遅れと build_manifest.py:61 だけが MacBook Air 待ち。

## 機体で縛るもの / 手順で縛るもの

機械で縛るのは「**その OS でしか起こせない失敗**」と「**器が配線されているか**」だけにする。
共有層が知ってよいのは OS（`platform.system()`）までで、役割名（MacBook Air / Mac mini / Windows）で
分岐する段を新しく足さない。役割は案件の `design/machine-scope.json` の宣言に閉じ、strict 既定 false
（`machine_scope.py:517`）なので1台運用のメンバーは machines に自機だけを全パスで宣言すれば全段が
自機で走る。これで memory `feedback_pc_role_division.md`「共同で使う仕組みにマシン別の権限分けを
組み込まない」（2026-08-25 追記）と矛盾しない。

機械化する6つ:
1. 眠っている pre-push（`core.hooksPath` 未設定）
2. submodule checkout が記録ピンと食い違う
3. Windows でだけ落ちる書き方（`str(Path)` を比較に使う・`encoding=` 抜け・素のコマンド名）
4. 受信箱の必須の節の存在（`shared_check`）
5. ビルド依頼の対象 commit（`inbox_tool --check-target`）
6. 変異試験の分母から無言で外れる道具

手順で縛るもの（段にしない）: ビルド → 大小2台のエミュレータ → 見たものを SESSION_LOG に1か所 →
配布 → INSTALL_GUIDE のリンク差し替え → 「依頼の項目 → 結果」の表で報告。および
「UI を直したら次のビルド依頼を書くまでが1つの作業」。
根拠は aub `DECISIONS.md:451-452`「検査の段にはしない。依頼の決まりとして書く」と
Issue #18「記録を関門にしない」。ただし**決まりの「存在」だけは機械で守る**（`shared_check --shared`）。

## 計画（7段）

| # | 何を | 機体 | モデル | 落として証明する方法 |
|---|---|---|---|---|
| 1 | `acceptance/windows.md` 第2回を書き、道具の穴5件を Issue に落とす | Windows単独 | Sonnet/low（題は Opus/medium） | `inbox_tool --self-test` が exit≠0、`portable_check --style` が `build_manifest.py:61` を出さないことを基準として残す |
| 2 | `portable_check` に `str(Path)` 比較の検出を実装（`--root` 複数指定も） | Windows単独 | Opus/medium | self-test の新しい落ちるケースで exit 1／`--root ../flash-compose/design/gen` が `build_manifest.py:61` を名指し／誤検出の負例0件 |
| 3 | 無言で緑になる3経路を塞ぐ（眠ったフック・checkout≠ピン・変異試験の無言スキップ） | Windows単独 | Opus/medium | aub で `stage_check --stages` が exit 1・`core.hooksPath` 設定で exit 0・`--unset` で再び exit 1／`mutation_test` が「測れなかった道具6本」を名指し |
| 4 | aub を main に揃えて pre-push を起こす | Windows（**要ユーザー承認**） | Sonnet/low | 揃える前後でピン・4道具の有無・偽の ref をフックに流して段が流れるかを比較 |
| 5 | MacBook Air へ依頼1本（`build_manifest.py:61` / verify.sh の step 形式化 / 移植性の段の配線 / python3 分岐の反転 / ピン59上げ / machine-scope に inbox と必須の節） | 依頼はWindows・実施はMacBook Air | 依頼文 Opus/medium（段の宣言判断は Fable/high） | 直る前 `--check` exit 1・`grep -c '^step '` = 0。直った後 exit 0 と `stage_check --stages` exit 0 |
| 6 | 依頼の決まりを配布・INSTALL_GUIDE・報告の表まで書き切る | Windows単独 | Opus/medium | 節の見出しを消すと `shared_check --shared` が exit 1／対象の無いビルド依頼で `inbox_tool --check-target` が exit 1 |
| 7 | preflight を `verify.sh` 再利用に寄せ、`mobile-harness-setup` に器の生成を足す | Windows単独 | Opus/medium | 空ディレクトリでウィザードを通し、`stage_check --stages` と `shared_check --shared` が exit 0。フックを消すと exit 1 |

## やらないと決めたこと

- **Windows 版ビルド確認スキル（flutter-android-build-check）を新設しない。** `~/.claude` はユーザーの
  3台にしか同期されず、そこに正本を置くと他メンバーの clone に届かない
- ビルド・配布の入口（`android_release.py` / `apk_upload.py`）を `design-harness/tools` に新設しない。
  `gate/conditions.json` の生きている6条件（1・4・5・7・8・9）にビルド・配布は無く、Drive の権限モデルが
  aub（共有ドライブ・固定ID・投稿者削除不可）と flash（My Drive・8MB分割・同名置換）で違う
- `upload_apk.py` 3本・ビルドレシピ3通りの共通化をしない（同じ理由）
- `emulator_check.py` の骨格と機体設定を分離して共有層へ回収しない。`PLAN.md:29` #18(b) に逆らう
- aub の `scripts/` をシムに置き換えない（作業ブランチでユーザーが同じ `scripts/` を触っている）
- verify.sh にビルド・エミュレータ・配布の段を足さない。`emulator_runs.json` を読む段も作らない
- 「UI を変えたのにビルド依頼が無い」を落とす検査を作らない（分母を機械が決められない）
- planttalk / qnd-database に適用しない（2026-09-05 ユーザー「変更中なのでやめてください」）

## ユーザー判断が要る点

1. **Windows でだけ落ちる `design/` の段の凌ぎ方。** 案A: いまのまま（直るまで Windows は push 不能。
   実績は 2026-09-04 から `--no-verify` 継続）。案B: `design/verify.sh` `design/stages.json`
   `design/harness` を `machine-scope.json` の shared に足し、期限つき緩和とピン上げを Windows も
   打てるようにする。**推奨は案B・確信度 中**
2. 段5の依頼をいつ出すか（PR #231 のマージ待ちと競合する）
3. 3台の器を生成する工程を `mobile-harness-setup`（本番のみ）に置くか、`app-project-init` にも置くか
4. ビルド・配布の道具の正本を作るか、どこに置くか
5. `--no-verify` と眠ったフックを `bash-guard.sh` で機械的に禁止するか
6. `machine-scope.json` を「権限」ではなく「環境の宣言」と位置づけ、`--check` を残す解釈でよいか
7. `app-pre-push:19-26` の「Mac からの main 直 push を止める」を 2026-09-05 の決定に合わせて外すか
8. **aub の作業ブランチを `git pull --ff-only origin main` で揃えてよいか**（段4 全体がこの承認に依存）
9. 1台で作業する他メンバー（機体名に macbook / mini を含まない Mac）を `machine_scope` がどう扱うか

## この案が覆る条件（確信度: 中）

(1) 足した検出が実際の Windows 非互換をほとんど捕まえない → Windows ランナーが要る
(2) 段5の依頼が数日単位で止まり、Windows が push 不能を繰り返す → 判断1の案B へ
(3) flash のピンを59上げたときに Windows でだけ落ちる段が複数出る → 段の結び直しでは足りない
(4) 案件が3つ以上になり `scripts/` の同名別実装を3回以上手で写す → 正本を作る判断
(5) `machine_scope` の担当宣言が他メンバーの1台運用を実際に止めた回数が積み上がる → 適用を縮める
(6) 次の Flutter 案件の予定が当面無い → 段7後半は先送りでよい

## 反証の結果（6件すべて耐えた）

| # | 主張 | 結果 |
|---|---|---|
| 1 | aub の origin/main のピンは2遅れ、作業ブランチが71遅れ | 耐えた（`git ls-tree` で再現） |
| 2 | 4道具は 99a98c7 にあり c329bc3 に無い。「71上げる作業」は存在しない | 耐えた（バイト数まで確認・パス移動も否定） |
| 3 | aub は `core.hooksPath` 未設定、flash は `.githooks` | 耐えた（global/system/local 全スコープと worktree も確認） |
| 4 | `stage_check` の `resolve_prepush` は眠ったフックを「配られている」と判定する | 耐えた（**訂正1件**: aub の `stage_check` 自体は別の理由で exit 1。正確には「眠ったフックという欠陥だけが無言で通る」） |
| 5 | `portable_check` は docstring の4項目のうち `str(Path)` 比較を実装していない | 耐えた（`check_style` に該当ノードが1つも無い） |
| 6 | `build_manifest.py:61` が Windows で exit 1 になる。`design/` は MacBook Air 担当 | 耐えた（**訂正1件**: 入るのは U+005C のバックスラッシュ。「円記号」は日本語環境での字形） |

---

# 第2部: Mac mini の軸で数え直した表

## (a) 事例の4分類と件数

事例 = その場で仕組み（手順・判断・道具・記録の形・確認の仕方）を新しく決めた、または決め直した出来事。
単なる作業報告（ビルドした・APK を上げた）は数えていません。

| 分類 | Windows | Mac mini | 差 |
|---|---:|---:|---|
| 機体の手順 | **17** | 25 | Windows が少ない |
| 判断の規約 | **39** | 29 | Windows が多い |
| 案件固有 | **12** | 17 | |
| 実測値 | **7** | 4 | |
| その他 | **3** | 4 | |
| **合計** | **78** | **79** | ほぼ同数 |

「その他」の3件は、分類に入らない**食い違い**です（「機体」の語が2義／main 直 push の規則が3文書で
食い違う／Windows に専属スキルが無い）。

## (b) それが「どこに書かれているか」

| 記載場所 | 件数 | 割合 |
|---|---:|---:|
| harness（`~/dev/design-harness/`） | 24 | 31% |
| script（`scripts/*.ps1` `*.py` の実装・コメント） | 23 | 29% |
| project-doc（案件の CLAUDE.md / DECISIONS.md / AGENTS.md） | 18 | 23% |
| **none**（記録の散文にしか無い） | 7 | 9% |
| **skill**（`~/.claude/skills/`） | **6** | **8%** |

分類ごとの内訳:

| | skill | harness | script | project-doc | none |
|---|---:|---:|---:|---:|---:|
| 機体の手順 | **0** | 4 | 12 | 0 | 1 |
| 判断の規約 | 6 | 16 | 3 | 14 | 0 |
| 案件固有 | 0 | 2 | 7 | 3 | 0 |
| 実測値 | 0 | 1 | 1 | 1 | 4 |
| その他 | 0 | 1 | 0 | 0 | 2 |

**いちばん重い数字は「機体の手順 17件のうち skill が 0件」です。** Windows の段取りは
12件が案件の `scripts/` の中（実装かコメント）にあり、案件をまたいで再利用できる場所には
ほとんど置かれていません。

`none` の判定は grep で確かめました（`~/.claude/skills` 配下を10キーワードで検索）。

| キーワード | skill | harness | script | project-doc | memory |
|---|---:|---:|---:|---:|---:|
| JAVA_TOOL_OPTIONS | 0 | 0 | 0 | 1（ARCHIVE） | 2 |
| tree-shake | 1 | 0 | 1 | 5 | 2 |
| truststore | 0 | 0 | 12 | 2 | 3 |
| gradlew --stop | 0 | 0 | 1 | 3 | 3 |
| WinError 10053 | 0 | 0 | 1 | 0 | 0 |
| 8MB 分割 | 0 | 0 | 3 | 6 | 2 |
| ビルド依頼を書くまでが1つの作業 | 0 | 0 | 0 | 1（DECISIONS） | 2 |
| PYTHONUTF8 | 0 | 6 | 1 | 5 | 3 |
| shutil.which | 0 | 2 | 2 | 2 | 1 |
| 検査は1回だけ回す | 0 | 0 | 1 | 1 | 2 |

**`~/.claude/skills` 全体で Windows 固有知見に一致したのは `tree-shake` の1件だけで、
それも iOS 用スキル（flutter-ios-build-check）の中でした。**

## (c) 2つの抜き出し

### 両案件（aub / flash）で繰り返した事例 — 型にできる最有力候補: 42件

そのうち、**両案件の `scripts/` に別実装として複製されている**ものが型にする価値が高い順:

| 事例 | flash | aub | 記載場所 |
|---|---|---|---|
| Norton の TLS に truststore を注入する | 10ファイル | 2ファイル | script（同じ7行の複製） |
| 文字コードの手当て（PYTHONUTF8 / reconfigure / errors=replace） | 2 | 2 | script + harness |
| 外部コマンドを `shutil.which` で解決する | 1 | 1 | harness + script |
| Drive への配布（`upload_apk.py`） | 4 | 2 | script（**差分472行＝約9割が別物**） |
| 送信の再試行 | 4 | 2 | script |

片方にしか無いもの（＝もう片方に穴）:

| 事例 | flash | aub |
|---|---|---|
| release preflight（main か・clean か・遅れていないか） | あり（.ps1 2本） | **無し**（4〜5コマンドの手作業） |
| 検査を1回だけ回して読み直す（`checks.py`） | **無し** | あり |
| エミュレータ大小2台の確認 | **無し** | あり |

### 繰り返しているのに `none` の事例 — 仕組みの穴: 2件

| # | 事例 | なぜ穴か |
|---|---|---|
| 77 | main 直 push の規則が3文書で食い違っている（machine-relay 2026-09-05「全機体可」／flash AGENTS.md「Mac は PR」／グローバル CLAUDE.md「Mac は直 push しない」） | どの文書も自分だけが正しいと書いている。フック（`app-pre-push:19-26`）は古い側を機械化したまま |
| 78 | Windows には Mac mini の `flutter-ios-build-check`（490行）に相当する専属スキルが無い | 機体の手順17件が skill に0件である原因。新しいセッションはスキルを経由せず、毎回 `scripts/` を読み直すか作り直す |

`none` 全7件（繰り返し以外も含む）:
JAVA_TOOL_OPTIONS のスペース問題 / self-test 44本中6本 NG / 変異試験の分母が Mac と違う /
python3 の有無の実態 / submodule ピンの遅れ / 上記2件

## (d) 読んだ範囲

**読んだもの**（8領域の並列調査＋本日の追加確認）:

| 対象 | 範囲 |
|---|---|
| design-harness | PLAN.md 614行・DESIGN.md 349行・POST-PUSH.md 49行・README.md 286行を全文。tools/ 48本のうち machine_scope / stage_check / shared_check / inbox_tool / situations_check / portable_check / pin_check / _utf8 を読解。attack/ 7本・acceptance/ 3本・ci/ 4本・templates/・gate/conditions.json・vocab/ |
| flash-compose | scripts/ 全18本・design/verify.sh 294行・design/machine-scope.json・design/gen/build_manifest.py・AGENTS.md・CLAUDE.md・DESIGN.md・MACHINE_HANDOFF.md・DECISIONS.md（見出し）・.claude/settings.json・.github/workflows/verify.yml |
| aub-familywalk | scripts/ 全5本・design/verify.sh 307行・design/machine-scope.json・AGENTS.md・DECISIONS.md・MACHINE_TASKS.md |
| スキル | mobile-harness-setup / mobile-implement-ui / app-project-init / machine-relay（SKILL + commander + worker）/ auto-mode / harness-issues / flutter-ios-build-check / flashcompose-daily-report / flutter-daily-report |
| GitHub Issue | design-harness の #6 / #18 / #46 の本文 |

**読まなかったもの（明示）**:

| ファイル | Windows の該当分 | 状況 |
|---|---:|---|
| aub-familywalk/SESSION_LOG.md | 58 件 | **全数未読**（1.08MB・19,165行。抜粋のみ） |
| flash-compose/SESSION_LOG.md | 53 件 | **全数未読**（抜粋のみ） |
| aub-familywalk/MACHINE_TASKS_ARCHIVE.md | 71 件 | **全数未読** |
| flash-compose/MACHINE_TASKS_ARCHIVE.md | 32 件 | 27 件を確認（Android ビルドし直しが 09-03〜04 で5回、という集計まで） |

したがって **78件は下限**です。上の214件の記録を全数読めば、特に「案件固有」と「実測値」は増えます。
Mac mini が79件を何から数えたかによって、単純比較できない可能性があります。

---

# 第3部: 4つの問いへの回答

## 問1. 読み手の有無 — `design/emulator_runs.json` を読む段は `design/verify.sh` にあるか

**ありません。Mac mini と同じ穴です。**

- aub の `design/verify.sh` に `emulator_runs` の文字列は1か所ありますが、**コメントです**（:125）。
  内容は「`machine_scope.py` の `owns()` が前方一致をどちら向きにも見るため、Windows が持つ
  `design/emulator_runs.json` が `design/` で始まる → Windows が design/ を担当していると誤判定した。
  だから鮮度の段の結び先を `design/` から `design/figma/` に直した」という**別の問題の説明**です。
  段（`step` 行）としては存在しません。
- リポジトリ全体で `emulator_runs` を参照するのは `design/verify.sh`（上のコメント）と
  `scripts/emulator_check.py` の2ファイルだけ。
- flash-compose には `emulator_runs.json` 自体がありません（一致するのは harness の
  `machine_scope.py` の self-test 文字列のみ）。

**では誰が読んでいるか。** 唯一の読み手は、**それを書いた `emulator_check.py` 自身**です。
前回確認した commit を基準に「今回見る画面」を算出するために自分で読み返します。
つまり記録は**書き手の中で閉じており、人も他の機体も読んでいません**。

これは意図された設計です（aub `DECISIONS.md:451-452`「検査の段にはしない。依頼の決まりとして書く」／
Issue #18「記録を『関門』にはしません。読めるようにするだけです」）。
ただし「読めるようにする」の**読み手が実在しない**状態が続いています。

Mac mini の `simulator_runs.json` が読む段ゼロなら、**共通の穴**です。

## 問2. 書き戻しの経路

**実例はあります。速いです。ただし自発はほぼゼロです。**

| 書き戻した先 | きっかけ | 指摘日 → 実装日 | 日数 |
|---|---|---|---|
| aub `scripts/emulator_check.py`（2台確認の道具） | ユーザー要望 | 2026-09-02 → 2026-09-02（6176d96） | **0日** |
| aub `scripts/checks.py`（1回だけ回す道具） | ユーザー指摘「いように時間がかかっていたがなぜ？」 | 2026-09-03 → 2026-09-03（d7ea99a） | **0日** |
| harness `tools/_utf8.py` `tools/portable_check.py` | 失敗（#6 / #52） | → 2026-09-04（b160f24） | 数日 |
| harness `tools/machine_scope.py` | 失敗（#36 / #37 Windows 常時NG） | → 2026-08-30（df984de） | 数日 |
| flash `scripts/verify_release_preflight.ps1` | 不明 | → 2026-08-16（544127f） | — |
| flash `scripts/build_and_upload.ps1` | 不明 | → 2026-07-13（64bd3e3） | — |

**きっかけの内訳（78件）**: 失敗 39 / ユーザー指摘・要望・確定・指示 20 / 不明 9 / 自発 9。
ただし**自発9件のうち7件は今日の調査そのもの**（self-test の NG・変異試験の分母・python3 の実態・
ピンの遅れ・規則の食い違い・専属スキルの不在）。
**日常業務の中で自発的に決めたものは2件だけ**（`devices.json` の形を揃えない判断／期限つき宣言で緩和する判断）
で、どちらも harness 側の整理の中で出たものです。

**書き戻し先の偏り**: harness 24 / script 23 / project-doc 18 に戻っている一方、
**skill には6件しか戻っていません**。Windows は「道具と案件のスクリプトには書き戻すが、
次の案件へ持ち出せる場所（スキル）には書き戻していない」状態です。

**測れなかったこと（未調査）**: この機体では `~/.claude` が git リポジトリではないため、
Mac mini が出した「スキルの全9コミットのきっかけ」「24日間の編集ゼロ」に相当する
コミット履歴の測定ができません。

## 問3. 決め直しの回数

日付が特定できたものだけで **11回**です。

**「何を見るか」— 3回**
1. 2026-09-02 大小2台のエミュレータで確認したい（新規）
2. 2026-09-03 最初に表示するのは大きい方1台だけ（**決め直し**）
3. 2026-09-04 修正のあった画面のみ確認すればいい（**決め直し**）

**「どう報告するか」— 4回**（Mac mini と同数）
1. 2026-08-14 Notion をやめて git 共有のファイルへ（他マシンが見に行かないため）
2. 2026-08-19 SESSION_LOG は先頭追記・見出しにマシン名と役割（試験で強制）
3. 2026-09-04 配信を先に・記録は後に1か所
4. 2026-09-04 報告は「依頼の項目 → 結果」の表で

**「どこへ配るか」— 2回**
1. 2026-09-02 URL 指定をやめてフォルダ ID で固定
2. 2026-09-04 過去のファイルは削除する（残すのは1件だけ）

**「誰が main に入れるか」— 2回**
1. 2026-08-19 自分が作った PR のマージは Mac でもよい
2. 2026-09-05 どのマシンも main へ直接 push してよい（PR 運用を廃止）

`4.` の系列は**まだ収束していません**（#77。3文書が食い違ったまま、フックは古い側を機械化）。

## 問4. Windows でだけ落ちるもの

| 事象 | いまの状態 |
|---|---|
| パス区切り（`str(Path)` が `\` を返し、`/` の台帳と食い違う） | **毎回踏む。** flash の `design/gen/build_manifest.py:61` で `verify.sh` が必ず落ち、2026-09-04 から `--no-verify` で押している（規則違反の回避策）。`design/` は MacBook Air 担当で Windows は直せない |
| pre-push が眠る（`core.hooksPath` 未設定） | **毎回踏む。** aub は今も未設定。`stage_check` もファイルの存在だけ見て緑にするので誰も気づかない |
| `issue_scan` が `~/.claude/projects` の Windows 符号化を知らない | **毎回踏む。** `harness-issues` が自案件の置き場を見つけられない |
| `gen_io` の CRLF 判定 | **毎回踏む**（self-test が Windows で NG） |
| Norton の TLS 検査（Python） | **回避策を手で打っている。** `truststore.inject_into_ssl()` の同じ7行を12ファイルに複製 |
| Norton の TLS 検査（Gradle） | **回避策を手で打っている。** `gradle.properties` は機体ローカルで git に乗らず、再現手順は `.ps1` のコメント3行だけ |
| DNS 断続失敗・WinError 10053/10054 | **回避策を実装に埋めた**（内側リトライ・8MB分割）が flash のみ。aub には無い |
| cp932 で日本語が化ける・道具が死ぬ | **直った**（harness 側は `_utf8` で 2本→0本）。ただし案件側スクリプトは各自対処のままで、`_utf8` を使えない |
| `.bat` の名前解決（flutter / adb） | **直った**（`shutil.which`） |
| CRLF による誤検知（担当外を変えたと数える） | **直った**（#41） |
| Figma トークンを持たない機体で必ず NG | **直った**（`machine_scope` で担当機体に結び直し） |
| カタログ鮮度の板挟み（#36） | **直った**（入口から import を辿って導出） |
| `python3` が無い前提 | **前提が古い。** この機体では `python` `py` `python3` すべて 3.14.3 に解決する。flash の `verify.sh:62-69` は「無ければ飛ばす」側に倒れており、**黙って検査しない**危険が残る |
| 共有層の CI に Windows ランナーが無い | **構造的に残る。** `attack.yml` は ubuntu のみ。Issue #6 が「実 Windows でないと出ない」と明記した2件（`.bat` 名前解決・cp932 既定）は、Windows 上で `verify.sh` を回すことだけが捕まえる |

---

# 第4部: Mac mini の結論との突き合わせ

Mac mini の主因2つについて、Windows 側の答えです。

## 主因1「出す記録を読む段が1つも無い」→ **共通の穴**

`emulator_runs.json` を読む段はゼロ。唯一の読み手は書き手自身（`emulator_check.py` が次に見る画面を
決めるために読む）。人も他の機体も読んでいません。
ただし Windows 側にはこれが**意図された決定**として記録されています
（aub `DECISIONS.md:451-452` / Issue #18「記録を関門にしない」・2026-09-03 ユーザー要望が起点）。
つまり「読む段が無い」ことは事故ではなく決定の結果です。**問題は決定の側ではなく、
「読めるようにする」と決めたのに読み手を用意しなかったこと**にあります。

## 主因2「学びを書き戻す経路に自発の段が無い」→ **共通**

きっかけ別で 失敗39 / ユーザー起点20 / 自発9（うち7件は今日の調査）。
**日常の自発は2件**です。ユーザー指摘からの書き戻しは同日（0日）で速いので、
遅いのではなく**自分からは始まらない**という形です。

## Windows 固有の差 — 線引きの材料

| | Mac mini | Windows |
|---|---|---|
| 専属スキル | `flutter-ios-build-check` 490行 | **無い** |
| スキルへの反映 | 反映済み20 / 部分13 / 未反映46（58%が未反映） | **skill にあるのは 6/78（8%）。機体の手順17件は0件** |
| 手順の置き場 | スキル | 案件の `scripts/`（12/17件） |

Mac mini は「スキルはあるが反映が58%止まり」、Windows は「**そもそもスキルが無い**」という差です。
分類の分布（機体の手順17 vs 25、判断の規約39 vs 29）もこれで説明がつきます。Windows は手順が
スキルとして言語化されていないぶん、**規約（判断の言葉）としてだけ残っている**と読めます。

## この突き合わせから言えること（Windows 側の見解）

1. **共有層（design-harness）に置くもの**: 「その OS でしか起こせない失敗」と「器が配線されているか」。
   今回の統合案の6つ（眠ったフック・ピンの食い違い・移植性・受信箱の節・依頼の対象 commit・
   変異試験の分母）はここに入ります。実装は Windows 単独で閉じます。
2. **機体ごとに分けるもの**: エミュレータ・シミュレータの起動（`#18(b)` で決定済み）、
   配布先の権限モデル、Norton・DNS のような環境固有の回避策。
3. **いま決まっていないのは3番目の層**です。「機体の手順」17件のうち skill 0件・script 12件が
   それに当たります。Mac mini は同じものをスキルに持ち、Windows は案件のスクリプトに持っています。
   **どちらの置き場を正とするかは、まだどこにも決定として書かれていません**（#78）。
   統合案では「新スキルを作らない」（`~/.claude` は他メンバーに届かないため）としましたが、
   これは Windows 側の判断であって、Mac mini 側の実態（スキルに置いている）と衝突します。
   **ここが2台の分析を統合するときの最初の論点になります。**
