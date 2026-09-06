# SESSION_LOG — design-harness

各セッションの作業を**先頭に**追記します（3台で git 共有）。
`### 作業概要` と `### 途中・引き継ぎ` は必須です。`### 戻したもの` は空でも「無し」と書きます。

このファイルは 2026-09-06 に Windows が新設しました（それまで design-harness には
セッションログがなく、記録は `PLAN.md` と `analysis/` に置かれていました）。

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
