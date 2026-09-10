# SESSION_LOG — design-harness

各セッションの作業を**先頭に**追記します（3台で git 共有）。
`### 作業概要` と `### 途中・引き継ぎ` は必須です。`### 戻したもの` は空でも「無し」と書きます。

このファイルは 2026-09-06 に Windows が新設しました（それまで design-harness には
セッションログがなく、記録は `PLAN.md` と `analysis/` に置かれていました）。

---

## 2026-09-10（MacBook Air / 司令塔）**確かめていない断定を道具から外した**（privacy_check）

### 作業概要

**`privacy_check.py` が「このリポジトリは公開です。」を無条件で出力していました。**
`isPrivate` も `visibility` も見ていません。

**実害（同日・実測）**: FlashEnglish（**非公開**）の作業ツリーに当てた出力を、
読んだ側（AI）がそのまま事実として受け取り、**「公開リポジトリに個人情報が 6 件」と
ユーザーへ誤って報告**しました。そのうえ**間違った前提で、非公開リポジトリの共有ファイル
3 本を書き換えて push**しました（`flash-compose@4000675`。中身の意味は変えず名前だけ伏せ字）。

**公開しているのは `design-harness` 1つだけです**（`gh repo view --json isPrivate` で確認）。
FlashEnglish・aub-familywalk・machine-relay・claude-dotfiles はすべて PRIVATE。
**公開リポジトリの privacy_check は 111 ファイルで 0 件です。**

**「確かめていないことを断定する」は、この仕組みがいちばん嫌う形です。**
しかも今回は**嘘の緊急性を作りました**。`hollow_check` が潰す「回っているのに空」より、
**空でないのに嘘を言う**ほうが読んだ人を遠くへ連れて行きます。

### 直したこと

    公開かどうかは **導く**（`gh repo view --json isPrivate`）
    取れなければ **言わない**（「公開かどうかは確かめられませんでした」）
    **`None` を「公開」に丸めない**

`gh` が無い機体でも落ちません（`OSError` を受け止める。**PATH を外して踏みました**）。

**self-test に3つ足しました。**

1. remote が無い場所で**断定していないか**（「このリポジトリは公開です」を出したら NG）
2. `visibility()` が remote の無い場所で `None` を返すか
3. **`gh` が無くても落ちないか**

**仕込んで落ちることを見ました。** `visibility(...) or "公開"` に戻す（直す前の形）と
self-test が NG になります。**戻して OK に戻ることも確かめました。**

**self-test の範囲でも1つ踏みました。** `PATH=/nonexistent` にすると `git` も消えるので、
`run_in`（一時 repo を作る）を同じブロックで呼ぶと**測りたいもの（gh の不在）ではなく
足場が壊れます**。範囲を `visibility()` だけに絞り、理由をコメントに残しました。

### 確かめたこと

- `privacy_check --self-test` rc=0／`stage_check` `hollow_check` `spacing_owner_check`
  `generated_check` の self-test も rc=0
- **変異試験**: 道具 48 本・落とす経路 239 本・素通り 93 本（**理由なし 0**）
- `readme_check` / `ci_path_check --sources` / `reachability_check` すべて OK
- 3つの実環境で出力を確かめた: **公開**（design-harness）・**非公開**（FlashEnglish）・
  **`gh` が無い**（PATH を外す）

### 戻したもの

無し。**`flash-compose@4000675` の伏せ字は戻していません**——非公開なので必要は
ありませんでしたが、伏せ字でも記録として読めるためです。**戻すかはユーザー判断。**

### 途中・引き継ぎ

`#109` の本文を書き直しました（「公開リポジトリに 6 件」という理由を取り下げ、
**「案件で回っていない」という中身だけ**を残した）。**段を入れるのはこの後**です。

---

## 2026-09-10（MacBook Air / 司令塔）用語を一般的な言い方に直した（「指紋」→「ハッシュ」）

### 作業概要

**ユーザー確定 2026-09-10。原文: 「一般的な言い方にしてくれれば良いです」「他のプロジェクトでもそうするようにしてください」。**

「指紋」は英語では SSH 鍵・GPG 鍵・TLS 証明書に対して使う正式な用語ですが、
**ここで指しているのはただのファイルのハッシュ**で、用途がずれていました。日本語の
現場では **ハッシュ / ダイジェスト / チェックサム** が普通の言い方です。

- 追跡ファイル **22 本**で置換（145 箇所）。`SESSION_LOG.md` は**過去の記録なので触りません**
- コードの中の名前（`template_digest()` / `fingerprint_parity.py` / `fingerprint/`）は
  **英語なのでそのまま**。改名していません

#### 読むほうだけ、旧い名前も見る

**JSON のキー**も `指紋` → `ハッシュ` に変えました（`design/stages.json` の
`$元ファイルの版`、`design/situations.json` の `確認`、`gate/conditions.json` の
`$生成元の…`）。ただし**書くのは新しい名前だけ、読むほうは両方見る**ようにしました。

- `stage_check.py`: `rec.get("ハッシュ") or rec.get("指紋")`
- `situations_check.py`: `(c.get("ハッシュ") or c.get("指紋")) != v["ハッシュ"]`
- `gen_gate.py`: `got.get('$生成元のハッシュ') or got.get('$生成元の指紋')`

**理由: 3台の版が揃わない期間に、旧いキーを持つ案件が落ちるのを避けるためです。**
落ちても直せるのは司令塔だけになり、**直せない関門**（#80・#103 と同じ形）になります。

### 確かめたこと

- 道具の self-test **全数** rc=0（落ち 0 本）
- `attack/` **7 本すべて rc=0**（`preamble_test.mjs` は 21 件 OK）
- `gen_gate.py --check` = 「関門の条件 6 件、正本と一致します」（正本 `gate/production-gate.md` に
  この語は無く、ハッシュは動いていません）

### 戻したもの

無し。

### 途中・引き継ぎ

**`ci/verify.sh.template` が変わったので、案件側の `design/stages.json` の
`$元ファイルの版` を打ち直す必要があります**（司令塔が同じ回で両案件ぶんやります）。

**他の2台への申し送り: 手で「指紋」と書かないでください。** 新しく書くときは
「ハッシュ」です。旧いキーは読めますが、**書き足すのは新しい名前だけ**にしてください。

---

## 2026-09-06（Mac mini / iOS ビルド）iOS ビルドの棚卸しと、項目表の改訂2件

### 作業概要

`build/inventory-schema.json` に沿って **iOS ビルドの実態**を書き出しました。Windows の
Android 分と突き合わせるための1段目です。**統合の可否は判定していません。**

- `analysis/build-ios-2026-09-06.json` — **377行**。依存 = none **102** / platform **41** /
  env 81 / hardware 65 / credential 14 / project 74。検証状態 measured 46行（12%）
- `analysis/build-ios-2026-09-06.md` — 作り方・数字・スキルに無い発見5件・書けなかったもの・
  Windows への申し送り

作り方: 領域を7つに分けて並列に読み出し（SKILL.md を3分割・道具・案件設定・
セッションログ2案件 32,099行）、**各領域を別の主体が敵対的に反証**しました。
評価軸は3つだけ（出典の実在・依存の分類・検証状態の誠実さ）。**116件を直しました。**
捨てた行は0で、代わりに出典を正しい位置へ差し替えています。

**`検証状態` は厳しく取りました。** 文書に「実測」と書いてあっても、この作業中に
走らせていなければ `read`。**ビルドは1度も走らせていません**（副作用の無い確認だけ:
`df` / `xcrun simctl list` / `ls` / `which` / `diff` / `git log`）。

#### 項目表の改訂1 — `依存` に `platform` を足した

反証から申し送りが出ました。「TestFlight 前に development 署名版を消す」を `none` に
したが、**Android は同じ鍵なら上書き更新できる**ので対称ではない、と。

`none` と `env` の2択だと、**プラットフォーム固有の事実が `none` に落ちて共有層に入り**、
「iOS でも Android でも同じ」という嘘の規約になります。`platform` を足し、`none` の
143行を18行ずつ8組で再監査、**`platform` に倒した行だけ別の主体が二次判定**しました。

**41行（29%）が iOS 固有でした。** 二次判定で2行が `none` に差し戻されています
（「破壊的な手を最後に回す」などは判断の規約なので共有できる）。
**再監査しなければ、41件の嘘の共通規約が共有層に入っていました。**

`案件差` にも `planttalk` / `全部` / `該当なし` を足しました（iOS には第3の案件
`~/planttalk` があり、Android 側には無い）。粒度の規約も明記しました。

#### 項目表の改訂2 — 検査を宣言から導く形にした（#85・close 済み）

指摘の3つのうち2つは改訂1で既に直っていましたが、**`所要: "はやい"` が exit 0 で
通る**のは本当でした。検査に一覧を持たせるのをやめ、項目表の `列の規約`（型・
語彙のある列・条件で必須になる列）から導く形にしました。**列を足すときは項目表に
足せば、検査は触らずに当たります。**

語彙の外だった列では条件必須の検査を重ねません（根が1つなのに2件報告すると、
直す人が2か所直そうとする。同じ形の二重判定を `machine_scope` で1度やっている・#29）。

#### 空振りの緑を2つ塞ぎました

- `attack/mutation_test.py` が `tools/*.py` しか変異させておらず、**新設した
  `build/inventory_check.py`（exit 1 で落とす検査）が無試験のまま緑**でした。
  MacBook Air が同時に同じ穴を直していたので（`7378acd`）、私の編集は捨てて
  相手側を採用しました
- その `return 2` の除外は `attack/broken_input_test.py` を根拠にしていましたが、
  **あの試験は `tools/*.py` の `--config` を持つ道具しか見ないので、この道具には
  届きません**。届かない試験を根拠にした除外は空振りなので、自己試験で塞ぎました（除外は消えた）
- 変異の走査は `build/` を見るのに `--allowed`（印の一覧）は `tools/` だけ、という
  ずれも `scanned_files()` に一本化しました（2か所で範囲を書くと必ずずれる）

検査（終了コードは直後に `rc=$?` で退避して確認）:

| 検査 | rc |
|---|---|
| `build/inventory_check.py --self-test` | 0 |
| `build/inventory_check.py analysis/build-ios-2026-09-06.json` | 0 |
| `attack/mutation_test.py` | 0（道具45本 / 落とす経路215本 / **理由なし素通り 0**） |
| `attack/mutation_test.py --self-test` | 0 |
| `attack/broken_input_test.py` | 0 |
| `tools/reachability_check.py` | 0 |
| `tools/generated_check.py --root . --subdir .` | 0 |
| `tools/readme_check.py` | 0 |

### 途中・引き継ぎ

- **2段目（突き合わせ）は Windows 待ちです。** Android 分は改訂1の**前**に書かれたので
  `platform` が 0行です。**統合の判定はこの列で決まる**ので、`none` の78行の再監査が
  済むまで突き合わせても意味がありません。依頼は `build/README.md` に書きました
- **Android 分に検査が2行落としています**（id 145・150 の `差あり` の中身が空）。
  何がどう違うかは測った本人しか書けないので、こちらでは埋めていません
- **`upload_apk.py` の差分行数が食い違います**（Mac mini 426 / Windows 472）。
  数え方が違うだけの可能性が高い（当方は行末の空白を落として `^[<>]` を数えた）。
  **どちらも未確定**なので、突き合わせのときに数え方を1つに決める必要があります
- **PlantTalk を1行も書けていません。** `~/planttalk` は実在し `DEVELOPMENT_TEAM` も
  入っていますが、`design/` も `SESSION_LOG.md` も `core.hooksPath` も無し（ハーネス未導入）。
  issue #80 が同じものを指しています
- **`MACHINE_TASKS.md` が design-harness にまだありません。** 本日 `attack/mutation_test.py` で
  **3回衝突**しました（3台が同じ1時間に push）。受信箱が無いので依頼を書く場所がありません。
  ただしこのリポジトリは公開なので、**セッションログに日々の作業を書き続ける公開範囲の判断が
  ユーザー未決**です（公開のまま／非公開化／仕組み専用の別リポジトリ の3択を提示済み）
- 「取得」が7行しかありません（Android は12行）。埋まる項目6つは `.md` の 4-2 に名指ししました

### 戻したもの

- `[harness]` `build/inventory-schema.json` の改訂1・2、`build/inventory_check.py`、
  `build/README.md`、`attack/mutation_test.py` の走査一本化、`analysis/build-ios-2026-09-06.{json,md}`
- `[project]` flash-compose をこの機体で最新化（4コミット遅れ→0）。submodule のピンを
  `280eddc` に同期し、`design/verify.sh` が **rc=0・735件**通ることを確認
- `[skill]` 無し（`flutter-ios-build-check` は棚卸しの対象なので触っていません。層分割は3段目）
- `[確認待ち]` 公開範囲の判断（受信箱の新設がこれ待ち）。`upload_apk.py` の数え方の統一

---

## 2026-09-06（Windows / データ・ロジック）Android ビルドの棚卸し

### 作業概要

`build/inventory-schema.json` の項目表に沿って、aub-familywalk と FlashEnglish の
**Android ビルドの実態**を書き出しました。Mac mini（iOS）と突き合わせるための1段目です。
**統合の可否は判定していません**（`build/README.md` の指示どおり、2 より先に 3 をやっていません）。

- `analysis/build-android-2026-09-06.json` — **198行**。依存 = none が **78行**
  （env 60 / project 28 / hardware 18 / credential 14）。検証状態 measured 23行
- `analysis/build-android-2026-09-06.md` — 環境の前提・踏んだ罠・案件差・該当が無い工程・
  署名の判定・書き出せなかったもの

実測したもの（この機体・2026-09-06）:

- **release ビルド 143 秒**（Gradle `assembleRelease` 137.7s）・exit 0・APK 77,354,859 バイト（73.8MB）。
  記録どおりのレシピ（`--release --target-platform android-arm64 --build-number --dart-define`）で実行。
  **Drive へは上げていません**
- **署名は `CN=Android Debug`**（SHA-256 `05b4a46b…`）。この機体の `~/.android/debug.keystore`
  （2026-04-10 生成）の指紋と**完全に一致**。つまり配布用 APK は**この機体でしか作れません**
- 環境: JDK 17.0.18 / Flutter 3.41.6 / Gradle wrapper 8.14（両案件同一）/ SDK は `C:\Android\sdk` /
  端末は cp932 / `adb` は PATH に無い

Mac mini の5つの数字を測り直し、**4つは一致、1つが食い違い**ました（`upload_apk.py` の差分行数:
Mac mini 426 / この機体 472）。truststore の 6ファイルは、`__pycache__` を除けば一致します。

検査（終了コードは直後に退避して確認）:

| 検査 | rc |
|---|---|
| `build/inventory_check.py analysis/build-android-2026-09-06.json` | 0 |
| `attack/mutation_test.py` | 0（道具40本 / 落とす経路188本 / 理由なし素通り **0**） |
| `tools/reachability_check.py` | 0 |
| `tools/generated_check.py --root .` | 0 |

### 途中・引き継ぎ

- **aub のビルドは走らせていません。** ユーザーが管理する作業ブランチ
  （`windows/androidのカメラをcamera2にする`）にチェックアウトされているため読むだけにしました。
  aub の所要・APK サイズ・実際の成否は**この回では未検証**です
- **所要は 198行中 1行しか実測していません**（flash の release ビルドのみ）。
  preflight 各段・`flutter test`・アップロードは測っていません
- 両案件の `SESSION_LOG.md`（aub は 18,000行超）と `MACHINE_TASKS_ARCHIVE.md` は**全数未読**です。
  grep で当たった箇所だけを読みました。aub の「宛先: Windows」30件のうち Android ビルドの依頼を7件読了
- エミュレータは1台も立ち上げていません。Drive の API も1回も叩いていません
- **W1〜W3（`analysis/windows-mechanism-2026-09-06.md` 第1部の7段）と #79 は着手していません。**
  ユーザーの指示で後ろに下げました。取り消しではありません
- 次は Mac mini の `analysis/build-ios-*.json` が揃うのを待ち、`build/README.md` の 2段目
  （`依存` の列で機械的に仕分ける）へ進みます。**仕分けは Mac mini の担当**です

### 戻したもの

- **[harness]** 項目表の `案件差` の語彙（`aub` / `flash` / `両方` / `差あり`）を
  `build/inventory_check.py` が検査していません。並列で書き出した5領域のうち **8行が `project`**
  （`依存` 側の語彙）を書いてきたので、こちらで直しました。**列は増えないので Mac mini 側の
  書き直しは不要**ですが、検査に足すかは判断が要ります。Mac mini が同じ道具を使用中のため、
  こちらでは**直していません**
- **[harness]** design-harness に `SESSION_LOG.md` がありませんでした（履歴上も一度も無し）。
  今回この形で新設しました。この形でよいか確認をお願いします
- **[確認待ち]** **署名**: 両案件の release APK は debug 鍵（機体ごとに自動生成される鍵）で
  署名されています。**取り残しではなく意図的な据え置き**と判定しました（aub `DECISIONS.md:121-123`・
  flash `MACHINE_TASKS_ARCHIVE.md:1040-1042`・aub `MACHINE_TASKS.md:21` に記録あり）。
  **Play Console に出す予定があるなら本番鍵の作成と署名し直しが要ります**（一度出した鍵は変更できないため、
  出す前に決める必要があります）。鍵は作っていません
- **[確認待ち]** `upload_apk.py` の差分行数が Mac mini（426）とこの機体（472）で食い違います。
  測り方（空白無視・共通行の数え方）の違いと見ていますが未確定です。数え方を揃えるなら
  コマンドを併記してください
- **[project]** aub: 配布リンクを Slack の DM で送る運用が文書間で食い違っています
  （`SESSION_LOG.md:3329` は送ると書き、`AGENTS.md:158-171` は Windows から送らないと確定）
- **[project]** FlashEnglish: `--dart-define=BUILD_REV` を渡しているのに、`lib/` に
  `String.fromEnvironment('BUILD_REV')` が**1件もありません**。渡した値はどこからも読まれていません
- **[project]** 両案件とも**実機で確かめた事実がファイルに残る経路がありません**
  （`emulator_runs.json` は仮想機のみ）。Windows が実機で確認した実例は3件ありますが、
  どうやって入れたかが記録に残っていません
