# Android ビルドの棚卸し（2026-09-06）

実施デバイス: **Windows (Dev-Logic)**
対象: aub-familywalk / FlashEnglish（`~/dev/flash-compose`）
対になる文書: `analysis/build-android-2026-09-06.json`（198行・`build/inventory_check.py` を通過）

**統合の可否は判定していません。** 各行の `依存` を事実として書いただけです。仕分けは iOS 側が揃ってから
`build/README.md` の規則で機械的に当ててください。

## 数字

| | 初版 | **再監査後** |
|---|---:|---:|
| 行数 | 198 | **198** |
| 依存 = none（統合の候補） | 78 | **64** |
| 依存 = **platform**（統合しない） | — | **12** |
| 依存 = env | 60 | **62** |
| 依存 = project | 28 | 28 |
| 依存 = hardware | 18 | 18 |
| 依存 = credential | 14 | 14 |
| 検証状態 measured | 23 | 23 |
| 所要を実測した行 | 1（release ビルド 143 秒） | 1 |

工程別: 前提 36 / 配布 39 / 仮想機の確認 29 / 検品 25 / 記録 18 / ビルド 16 / 取得 12 / 報告 9 /
依存解決 8 / 実機の確認 6。

5領域（flash の .ps1 経路・aub の手作業経路・仮想機/実機/記録・配布の2実装比較・罠と前提）を並列で
書き出した 222 行から、**情報量が厳密に少ない重複 28 行**を畳んで 194 行、主担当の実測 4 行を足して 198 行です。

---

## 0. 再監査（2026-09-06・項目表の改訂1 に合わせた追記）

初版は `platform` の枠より前に書いたので、`platform` が 0 行でした。`依存 = none` の 78 行を
**「iOS に置き換えても同じことが言えるか」**で見直し、**12 行を `platform` に倒しました**（15%）。
iOS 側は 143 行中 41 行（29%）だったので、こちらのほうが低い割合です。初版の時点で Android 固有の
機構の多くを既に `env` / `hardware` / `project` に振っていたためだと見ています。

**判断の規約（記録の書き方・報告の形・見る順番）は `none` のままにしました。**
ここを倒すと統合できるものが分かれます。

| id | 手順 | iOS では何が違うか |
|---|---|---|
| 167 | release APK は debug 鍵で署名される（keystore が無い） | **iOS は署名なしでは release ビルド自体ができない。**証明書と provisioning profile が要る。「debug 鍵のまま配る」が成立しない |
| 74 | `flutter build apk --release`・分割しない | `apk` は Android 固有。`--split-per-abi` の ABI に当たる概念が iOS に無い |
| 195 | 記録どおりのレシピ（`--target-platform android-arm64`） | iOS は `flutter build ios` / `ipa`。`--target-platform` に当たる指定が無い |
| 83 | `adb install -r` → `pm grant` → `am start` | iOS は `xcrun simctl install` / `launch`。実行時の許可を先に与える仕組みが無い（初回起動時のダイアログ） |
| 86 | 立ち上げ直したらアプリを入れ直す（`-no-snapshot-save`） | iOS シミュレータは shutdown してもアプリが残る（消すのは `erase`） |
| 72 | 版番号は pubspec → `flutter.versionCode` / `versionName` 経由 | iOS は `CFBundleVersion` / `CFBundleShortVersionString`（Info.plist と project.pbxproj 経由） |
| 165 | Gradle wrapper 8.14 | Gradle は Android 固有。iOS は CocoaPods と Xcode で、wrapper で版を固定する仕組みが無い |
| 166 | `android/gradle.properties` | 同上（Podfile と Build Settings に分かれる） |
| 97 | `emulator_runs.json`（`apk_digest` を持つ） | iOS は `simulator_runs.json` で、指紋の対象が `.app` / `.ipa` |
| 98 | `build/emulator-check.json` | AVD 名・density に当たる項目が iOS のシミュレータに無い |
| 137 | Android と iOS で記録の形が違う | 行の主張そのものがプラットフォーム差 |
| 44 | `-dirty` は「成果物の中身に入る場所」の未コミットだけで判定 | 見るパスの集合が違う。iOS は `android/` ではなく `ios/`（`Runner.xcodeproj`・`Info.plist`・`Podfile.lock`） |

**あわせて 2 行を `env` に直しました**（`platform` ではありません）。id 2・4 の PowerShell の作法
（`Set-StrictMode` / `$ErrorActionPreference` / `Invoke-Native` ラッパ）は、**機体の shell を替えると
変わる**ので `env` です。Mac 側の同じ役目は `set -euo pipefail` と `$?` になります。

**粒度の印を 4 行に付けました**（id 3・38・39・126）。判断は対称なのに実体が Android / PowerShell
固有という混在行です。項目表の「粒度」の規約に従い、行を割らずに `罠` へ
「対称性あり・統合時に分割が要る」と書いています。**割るのは 2 段目の担当**です。

検査が落としていた 2 行（id 145・150 の `案件差の中身` が空）も埋めました。中身は `実体` の列に
測ってあったものを書き下ろしたので、新しく測り直してはいません。

---

## 1. Mac mini 側の数字を、この機体で測り直した

| 見たもの | Mac mini | この機体の実測 | 判定 |
|---|---|---|---|
| Android ビルドのスキル | 0本 | **0本** | 一致（`~/.claude/skills` を grep: gradle 0 / Play Console 0 / signingConfig 0 / keystore 0。`apk`/`aab` の一致は auto-mode・machine-relay・coten-radio の4ファイルで、いずれもビルド手順ではない） |
| `upload_apk.py` の行数 | aub 235 / flash 303 | **一致** | 一致 |
| 同 差分行数 | 426 | **472** | **食い違い**（下記） |
| flash にあって aub に無い | `verify_release_preflight.ps1` 89行・`build_and_upload.ps1` 66行 | **一致**（aub の `.ps1` は 0本） | 一致 |
| truststore の同じ処理 | 6ファイル（flash 5・aub 1） | **6ファイル（flash 5・aub 1）** | 一致 |
| `signingConfig` | 両案件とも release が `signingConfigs.getByName("debug")`・`build.gradle.kts:37` | **一致** | 一致 |

**差分行数の食い違いについて。** こちらは `diff aub flash | grep -c "^[<>]"` で **472** でした（削除 235 行 + 追加 303 行 −
共通行）。Mac mini の 426 との差は、比較の取り方（空白無視・共通行の数え方・`diff` の実装）の違いだと思われます。
**どちらが正しいかはこの機体では決められません**（数え方を揃えるなら、どのコマンドで測ったかを併記してください）。
なお私が最初に truststore を「flash 10 / aub 2」と数えたのは `__pycache__` の `.pyc` を含めていたためで、
除外すると Mac mini と同じ 6 ファイルになります。

---

## 2. 環境の前提（すべてこの機体での実測）

| | 値 | 出どころ |
|---|---|---|
| JDK | Microsoft OpenJDK **17.0.18** LTS | `java -version` |
| Flutter | **3.41.6** stable（`C:\src\flutter\bin\flutter`。engine 5cdd3277） | `flutter --version` |
| Gradle wrapper | **8.14-all**（両案件とも同一） | `gradle-wrapper.properties` |
| `android/gradle.properties` | 両案件とも同一（`-Xmx8G -XX:MaxMetaspaceSize=4G ...` と `android.useAndroidX=true` の2行） | 実ファイル |
| Android SDK | `ANDROID_HOME` = `ANDROID_SDK_ROOT` = **`C:\Android\sdk`** | 環境変数 |
| adb | **PATH に無い。** 実体は `C:\Android\sdk\platform-tools\adb.exe` | `command -v adb` |
| Python | `python` / `python3` / `py` の**3つとも動く**（3.14.3） | 実行 |
| 端末の文字コード | **cp932。`PYTHONUTF8` は既定で未設定** | 実行 |
| `JAVA_TOOL_OPTIONS` | **未設定（空）。ここにパスを入れてはいけない** | `echo` |

**Norton の TLS 検査は今も生きています。** `dl.google.com` の証明書チェーンの根が
`CN=Norton Web/Mail Shield Root`（SHA-1 `2AD0FF5594D6A5E7828C3775AE71FAC033229B66`）に差し替わっていることを
確認しました。回避策は2系統あり、**どちらもリポジトリの外**にあります。

- **Gradle**: `~/.gradle/gradle.properties` が全ビルドに `trustStore` を差す。実体は
  `~/.gradle/gradle-truststore.jks`（170,514 バイト・2026-08-27 更新）。ファイル冒頭に
  「truststore は planttalk で作成したものを流用」と書かれています。**3台同期の外・git の外**で、
  再現手順はどのリポジトリにもありません
- **Python**: `truststore.inject_into_ssl()` を各スクリプトが個別に呼ぶ（6ファイルに同じ処理）。
  `certifi` のバンドルだけでは今も検証に失敗します

**DNS は断続的に落ちます。** ただし本セッションの 10 回はすべて成功したので、**再現はしていません**
（2026-09-04 の実測記録に依っています）。回避は「スクリプトの内側でリトライする」で、**外から回し直すと
同じ APK が二重に上がる**ため両案件とも内側に持たせています。

---

## 3. 踏んだ罠

| 事象 | いまの状態 | 出典 |
|---|---|---|
| `.bat` の名前解決（`flutter` は `flutter.bat`。`CreateProcess` が解決しない） | **直った**（`shutil.which` で解決）。ただし **PowerShell 経由なら効くので、Python の `subprocess` だけが踏む** | aub `checks.py`・`emulator_check.py` |
| cp932 で道具が死ぬ | **案件で割れている。** 同じ道具・同じコマンドで **aub は `UnicodeEncodeError` で死に、flash は死なない**。原因は harness submodule のピン違い（aub `c329bc3` / flash `6283274`）。`verify.sh` が先頭で `PYTHONUTF8=1` を export するため、**verify.sh 経由では覆い隠される** | 本セッションで両案件を実行 |
| `read_text` / `write_text` の `encoding` 抜け | 直った（aub は静的検査で見張っている） | aub `design/gen/text_encoding_check.py` |
| `str(Path)` が `\` を返し `/` の許可リストと一致しない | **直った**（`as_posix()` に統一）。ただし FlashEnglish の `design/gen/build_manifest.py:61` には**同じ形が残っている**（W2 の課題。ここでは直さない） | 本セッション |
| CRLF | **作業ツリーの改行が2案件で違う**（aub は全部 CRLF・flash は `design/` が LF で `scripts/` が CRLF。git の blob はどちらも LF）。`verify.sh` が `foreground.svg` を LF で書き戻すため、`core.autocrlf=true` のこの機体では **中身の差分0行なのに `machine_scope` が「担当外を変更」と見て NG** になる | aub `verify.sh` |
| CRLF の shell script | **壊れなかった**（確かめて再現しなかったこと。この Git Bash では問題なし） | 本セッションで検証 |
| Gradle の PKIX | **回避策を手で打っている**（上記）。証明書を足しても**デーモンが古い truststore を掴んだままだと効かない**ので `gradlew --stop` が要る | `build_and_upload.ps1:14-16` |
| Gradle のキャッシュ破損 | **実例が見つからなかった。** 両案件の `.md`/`.py`/`.sh`/`.ps1` を「キャッシュ破損 / corrupt / rm -rf ~/.gradle」で探して0件。`gradlew --stop` の用例2件はどちらもキャッシュ破損ではなく truststore の掴み直しとメモリ解放 | 本セッション |
| Gradle デーモンがメモリを占有 | **毎回踏む。** ビルド直後にエミュレータ2台を回すと常駐が 2GB 居座り、空きが 0.7GB まで落ちて **Android ごと落ちる**。`./android/gradlew --stop` を挟む | aub `emulator_check.py` |
| 107MB の APK を1本で送ると `WinError 10053` | **回避策を実装に埋めた**（8MB 分割 resumable）。**flash だけ。** aub は分割しない | flash `upload_apk.py` |
| `JAVA_TOOL_OPTIONS` がスペースで壊れる | 未設定のまま（触らないのが対処） | `MACHINE_TASKS_ARCHIVE` |
| Git Bash からスペース入りパスの `.bat` を呼ぶと壊れる | **本セッションで踏んだ。** `apksigner.bat` を呼ぶときに PowerShell の `&` 演算子を使って回避 | 本セッション |
| bash のヒアドキュメントで JSON 中の `\\` が1本失われる | 本セッションでも踏んだ（Write ツールで書き直して回避） | 2026-08-28 の受け入れ記録にも同じ記載 |

---

## 4. 案件で違うところ

| | FlashEnglish | aub-familywalk |
|---|---|---|
| 入口 | `build_and_upload.ps1` 1本（`-Debug` / `-Public`） | **`.ps1` が1本も無い。**全工程を人が手で打つ |
| 配布前の関門 | `verify_release_preflight.ps1` が **15段**（main か・未コミット・origin より遅れ・design-systems のクリーンさと ahead・`pull --ff-only`・トークン `#f8f6f5` の照合・`pub get`・`analyze`・`token_sync_test`・`flutter test`・`design_check`） | `checks.py`（analyze + test + `verify.sh` を**1回ずつ**回してログに落とす）。**preflight に相当するものは無い** |
| ビルド | `--release --target-platform android-arm64 --build-number=<yyyyMMddHH> --dart-define=BUILD_REV=<SHA>` | `--release` のみ。**分割しない**（1ファイルのほうが渡しやすい、と依頼で明記） |
| 版番号 | `--build-number` に日時10桁。pubspec は `1.0.0+1` のまま | **pubspec の版は触らない**（MacBook Air が上げる。iOS と共有のため2台が別々に上げると衝突する） |
| 配布先 | **My Drive**。フォルダ「FlashEnglish APK」を**名前で検索**し、無ければ作る | **共有ドライブ**。フォルダ ID `1Xxzf…` で**固定**（名前で探さない） |
| 権限モデル | 自分のドライブなので作成も削除も自分でできる | **投稿者は `canTrash: false` で 403。自分が上げたものも消せない。**道具は残っているものを名指しで並べるだけで、片付けは人 |
| 送信の堅牢化 | 8MB 分割 resumable・塊ごと最大8回・**一時エラー（429/5xx）だけ**送り直す | 分割なし・12回×3秒のリトライ・**種類で見分けずに**送り直す |
| 同名の扱い | 照合が通ってから**旧版を消す** | 同名があれば**上げない**（`--force` で上書き） |
| 上げた後 | Drive を引き直して4点照合（trashed でない・名前・親・サイズ） | **照合しない**（`create` の応答をそのまま信じる） |
| 公開リンク | `--public` で anyone/reader | 相当が無い（`webViewLink` を出すだけ） |
| 仮想機の確認 | **段が無い**（ビルド→Drive で閉じている） | `emulator_check.py` が両端2台（360x640dp / 448x997dp） |
| 配布後 | なし | `docs/INSTALL_GUIDE.md` のリンク差し替えまでが仕事（**APK を差し替えたのと同じコミットの中で**） |

APK の大きさも違います（flash の release/arm64 は**実測 73.8MB**、aub は記録上 46.7MB）。
**aub がチャンク分割を持たない理由は分かりません。** 踏んでいないだけなのか実装が漏れているのか、
この機体では判定できませんでした。

---

## 5. 該当が無い工程（無いこと自体が発見）

| 工程 | どこに無いか | 分かっていること |
|---|---|---|
| **仮想機の確認** | **FlashEnglish に無い** | `build_and_upload.ps1`・`verify_release_preflight.ps1`・`upload_apk.py` のどこにも `adb` / `emulator` の呼び出しが無い。Windows 側の Android 経路は「ビルドして Drive に上げる」までで閉じている |
| **実機の確認** | **両案件とも道具が無い** | aub は実例が3件あるが「どうやって入れたか」が節に書かれていない（1件だけ無線 adb `192.168.3.148:5555` の記録あり）。flash は `upload_apk.py` の docstring に文章で1行あるだけ |
| **実機の記録** | 両案件とも無い | `emulator_runs.json`（仮想機）はあるが、**実機で確かめた事実がファイルに残る経路が無い** |
| **ビルドの識別** | flash | `--dart-define=BUILD_REV` を渡しているのに、`lib/` に `String.fromEnvironment('BUILD_REV')` が**1件も無い**。渡した値はどこからも読まれていない |

**この機体には Android の実機が繋がっていません**（`adb` が PATH に無く、aub の記録も「`adb devices` が空・
実機の接続をお願いした」となっています）。歩数の中心要件（アプリを閉じていても測る）は
エミュレータでは原理的に確認できないため、実機の確認は Windows 側で自動化できていません。

---

## 6. 署名の判定（依頼の 5）

**判定: 取り残しではなく、認識されたうえでの意図的な据え置きです。ただしコードには何も書かれていないので、
コードだけ読むと取り残しに見えます。** 直していません。

実測（この機体・2026-09-06）:

- 出来た release APK の署名は `V2 Signer: certificate DN: C=US, O=Android, CN=Android Debug`、
  SHA-256 `05b4a46b02ad4604f58d21b7a29721d6e8c0537b1440a61072083f97e7d567b1`
- この指紋は **この機体の `~/.android/debug.keystore`（2026-04-10 生成）の指紋と完全に一致**しました
- release 用の `key.properties` / `*.jks` / `*.keystore` は**どちらの案件にも1つもありません**
- `build.gradle.kts:33-38` は Flutter の雛形のコメント（`// TODO: Add your own signing config for the
  release build.` / `// Signing with the debug keys for now, so flutter run --release works.`）が
  **両案件とも一字一句そのまま**残っています

意図的だと判断した根拠（すべて文書の記述）:

1. aub `DECISIONS.md:121-123`: 「現状 release APK は **debug 鍵で署名されている**（Flutter の既定のまま）。
   … **必ず同じマシン（Windows）で作る**こと。別マシンで作り直すと署名が変わり…」
   — 状態を把握したうえで、運用上の含意まで書いています
2. flash `MACHINE_TASKS_ARCHIVE.md:1040-1042`: 「いまは署名の設定を入れていないので、`--release` は
   デバッグ鍵で通ります。**ストアに出す段になったら鍵の作成が要ります**（**鍵の作業は AI はやりません**）」
3. aub `MACHINE_TASKS.md:21`: 署名は「**人にしかできないこと**（実機・署名・トークン・契約）」に分類

**運用上いま効いている制約（これが `依存 = credential` の実体です）。**
debug 鍵は Android SDK が**機体ごとに自動生成**するもので、機体が違えば指紋も違います。つまり
**配布用 APK は Windows でしか作れません**（別機体で作ると署名が変わり、参加者は入れ直しになる）。
aub の「必ず同じマシンで作る」はこの性質を正しく捉えています。**Mac mini が同じ APK を作ることはできません。**

**ユーザー判断に上げる点**: Play Console に出す予定があるなら、本番鍵を作って署名し直す必要があります
（一度ストアに出した鍵は変更できないため、出す前に決める必要があります）。予定が無ければ、
いまのままで実害はありません。**鍵は作っていません。**

---

## 7. 書き出せなかったものと、その理由

**測っていないもの**

- **所要は 198 行中 1 行しか実測していません**（flash の release ビルド 143 秒）。
  preflight の各段・`flutter test`・アップロードの所要は測っていません
- **aub のビルドは走らせていません。** ユーザーが管理する作業ブランチ
  （`windows/androidのカメラをcamera2にする`）にチェックアウトされているため、読むだけにしました。
  したがって **aub の所要・APK サイズ・実際の成否はこの回では未検証**です
- 過去ログにある数字（aub のビルド 120 秒・検査 80 秒・画面歩き 7分5秒・APK 46.7MB、
  flash の 78MB / 249MB / 107MB）は**他者の実測**で、この回のものではありません
- **エミュレータは1台も立ち上げていません。** 仮想機の確認の 29 行はすべてコードと文書の読み取りです
- **Drive の API を1回も叩いていません。** フォルダの実在・中身・実際の権限は未確認です。
  flash の「FlashEnglish APK」と AGENTS.md の「flash-compose APK」のどちらが実在するかも未確認です
- **DNS の断続失敗は再現していません**（本セッションの 10 回はすべて成功）
- **Gradle の PKIX が今このコマンドで通ることは、Gradle 経由では確かめていません。**
  ただし release ビルドが exit 0 で通ったので、結果的に TLS は通っています

**読んでいないもの**

- **両案件の `SESSION_LOG.md`（aub は 1.08MB・18,000行超）と `MACHINE_TASKS_ARCHIVE.md`（476KB）は
  全数を読んでいません。** grep で当たりを付けた箇所だけです。aub の「宛先: Windows」は見出しで30件あり、
  そのうち Android ビルドの依頼を新しい順に**7件**読みました。したがって「無い」と書いたもの
  （`.ps1`・`--split-per-abi`・`pub get` の明示手順）は、grep の語に掛からない書き方で存在する可能性が残ります
- `~/.android/debug.keystore` と `~/.gradle/gradle-truststore.jks` は**指紋だけ**見て中身は開いていません。
  `credentials.json` / `token.json` / `~/.claude/.env` は存在と大きさだけで、中身は読んでいません
- ルールの判定本体（`design_check.py` の 1-732 行）、`token_sync_test.dart`、
  `figma_extract.py` / `figma_freshness.py` / `page_scope_check.py` の中身は読んでいません（配布経路から呼ばれないため）

**判定できなかったもの**

- **aub が 8MB 分割を持たない理由**（踏んでいないだけか、実装が漏れているか）
- **AVD の `hw.ramSize` が 2048 → 4096 に変わった経緯**（リポジトリにも memory にも記録が無い）
- **配布リンクを Slack の DM で送る運用の可否**。aub `SESSION_LOG.md:3329` が「リンクを Slack の DM で
  お送りします」と書き、`AGENTS.md:158-171` が「Windows から Slack へ送らない」と確定していて、
  文書どうしが食い違ったままです
- **`upload_apk.py` の差分行数が Mac mini（426）と食い違う理由**（測り方の違いと推測していますが未確定）

**この機体では原理的にできないこと**

- Android 実機での確認（実機が繋がっていない）
- iOS 側の経路（Mac mini の担当）
