# Web案件のデザインハーネスを導入する

共有側は検査・書き出し器・導入手順を持ちます。案件側はFigmaの参照先、対応表、生成器、照合試験、既存トークンを持ちます。QnD固有のダーク禁止・廃止クラス名は、新しい案件へコピーしません。

## 1. 作業の基準を確認する

ブランチ、コミット、作業ツリー、案件のAGENTS.mdとDESIGN.mdを確認します。既存の変更を上書きせず、作業ブランチで進めます。Figmaの許可ページと既存トークン・部品の対応表を使います。

案件の `design/harness` はdesign-harnessのsubmoduleです。`design/design_check.py` は共有エンジンへ委譲するシムです。

## 2. 検査器を準備する

Python 3.12以降とNode 22以降を使います。React対象があるときは、ハーネスのディレクトリで実行します。

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run test:react
python3 tools/rules_selftest.py rules/web.json
python3 tools/seed_check.py --rules rules/web.json --seeds seeds/web
```

React対象が無い案件でも、共有側のReact試験を確認するときは依存が必要です。TSX/JSXのある案件でNode・解析器が不足した場合は、解析できなかったと報告して停止します。

## 3. 案件の禁止ルールを作る

`design/rules.json` は共通Webルールを継承し、案件固有の禁止だけを追加します。共通のルールIDを上書きしません。TSX/JSXは共通のReactルールの対象拡張子にも入るため、子の拡張子指定が古くてもReact検査は届きます。

```json
{
  "extends": ["harness/rules/web.json"],
  "rules": [],
  "exclude_paths": ["design/harness", "design/seeds", "node_modules", "dist"],
  "exclude_files": ["tokens.css", "tokens.json"],
  "ignore_reason_min": 10,
  "expected_rules": 13
}
```

共通の `seeds/web/` を案件の `design/seeds/` に置き、案件固有のルールにも種を追加します。全体走査で実際の対象ファイル数を確認し、`expected_targets` に記録します。取得・生成した値だけを持つトークン定義は除外しますが、手書きの画面を丸ごと除外しません。

```sh
python3 design/design_check.py --all
python3 design/harness/tools/seed_check.py --rules design/rules.json --seeds design/seeds
```

TSX/JSXでは、色・余白・角丸を構文から読みます。解析できた数は合格件数ではありません。動的値、別の.tsへの参照、未知のスプレッド、構文エラーがあれば、場所・理由・未解析件数を出して停止します。

意味付きTailwindクラスとトークンの対応、CSS変数の存在・用途・Figmaとの対応は、この検査では照合していません。対応表と数値照合で別に検証してください。React Native、字体・線幅など色・余白・角丸以外のReact属性は対応済みと扱いません。

## 4. Figmaを機械で書き出す

- `exporters/export_variables.js` はVariablesの全モードとText/Effect/Color Stylesを読みます。コレクションを絞るときは `COLLECTION_SCOPE` に案件の名前を指定します。戻りの `collections` は名前をキーとする辞書です。既存生成器が配列形式を読む場合は読み取りの接続が必要です。
- `exporters/export_components.js` は部品の全変異を読みます。
- `exporters/export_frames.js` は画面のノード木、SLOTの差し込み、上書き、マスク、配置制約、線幅、箇条書き区間を読みます。
- `$meta.読めなかったもの` は案件側の限界宣言へ届けます。取得不能な字下げの描画実寸や、照合できない文字変数を推測で補いません。

文字区間は [FigmaのgetStyledTextSegments](https://developers.figma.com/docs/plugins/api/properties/TextNode-getstyledtextsegments/) のlistOptionsとindentationを使います。

再現性検査の設定に `frames_export` を指定すると、書き出しが報告した字下げ実寸の未検証を `check_render_gaps.py` が「△」として出します。パスは設定ファイルからの相対です。

書き出しはFigmaから返ったものを保存し、トークン・部品・画面の生成器の入力にします。対応表はID・名前と実装の接続だけを持ち、見た目の期待値を手で写しません。

## 5. 大きい画面を分割して取得する

`export_frames.js` の `TRANSFER_MODE` を `manifest` にすると、画面ID・名前・節・全行数・行ハッシュ・全体ハッシュを返します。`ONLY_IDS` で対象画面を絞れます。

次に `TRANSFER_MODE` を `rows` にし、`ROW_INDICES` に必要な行の番号を指定します。範囲が大きすぎる場合は、転送前に分割が必要だと説明します。古い書き出しと行ハッシュを照合し、変わった行だけ取得できます。

```sh
python3 design/harness/tools/frame_io.py --manifest manifest.json --chunks rows-a.json rows-b.json --previous design/figma/frames.json
```

標準出力に復元した完全なJSONが出ます。欠けた行・異なる版・誤ったハッシュがある場合は停止します。成功した出力だけを案件の保存手順で保存します。部分取得をそのままframes.jsonとして扱いません。

画面の生成器は `frame_io.screen_mapping(frames, mapping, frame_id)` で対応表を引けます。IDを優先し、名前だけの照合で同名画面があれば停止します。古い部分一致の宣言は、案件側でIDまたは一意な名前へ移行します。

## 6. 改名と鮮度の更新を確認する

```sh
python3 design/harness/tools/figma_change_check.py --before old-components.json --after design/figma/components.json --references design/component-map.json design/screen-map.json site
```

同じノードIDの名前・種類の変更と古い参照候補を出します。候補は文字列検索で、意味の判定ではありません。IDが変わる再作成は自動で対応付けません。

線幅・マスク・固定位置をハッシュに含める変更で、以前の鮮度記録とハッシュが食い違います。まず書き出し本体と生成物を更新し、案件の `figma_freshness.py --update` で記録し直します。ハッシュ方式だけが変わったことを確認した場合に限り、既存手順の `--force` を使います。Figmaの未反映まで強制的に通しません。

## 7. Webの照合検査を組む

色・寸法・ぼかし・変異の期待値は、variables.json・frames.jsonまたはそこから機械生成した出力を読みます。測定対象を生成する実装コードから期待値を作りません。

`design/expectations.json` では、測定スクリプトも検査対象として宣言します。

```json
{
  "dirs": ["scripts/measure"],
  "export_globs": ["design/figma/", "variables.json", "frames.json"],
  "check_web_literals": true
}
```

```sh
python3 design/harness/tools/expectation_source_check.py --config design/expectations.json
```

この追加検査はJavaScriptの比較式と、evaluateへ渡す文字列内の直書きを見ます。関数・ファイルをまたぐ期待値の出どころは追跡していません。未解析件数があれば、コード全体を検証済みと報告しません。

## 8. ChromiumとWebKitで操作と描画を見る

ハーネスのディレクトリでブラウザを用意します。LinuxではOSの依存も必要です。

```sh
npx --no-install playwright install chromium webkit
node --test attack/web_browser_test.mjs
```

案件側はローカルプレビューのURLと対象を `design/web-browser.json` に指定します。scrollとvectorsは両方必須です。ブラウザはホイール操作でスクロール位置が変わるか、VECTORを隠すと画素が変わるかを測ります。

```json
{
  "pages": [{
    "url": "http://127.0.0.1:8802/index.html",
    "scroll": ["[data-scroll-container]"],
    "vectors": ["[data-primary-vector]"]
  }]
}
```

```sh
node design/harness/engine/web_browser_check.mjs design/web-browser.json
```

ブラウザが無ければ未検証として終了コード2で停止します。Safariの操作バー、iOS実機、指定外の画面・要素は未検証と出します。画像の印象による見た目の合否は判断しません。

配布版Chromiumを取得できず既存のChromeを使う場合は、設定に `chromiumChannel: "chrome"` を指定します。試験固定具では `HARNESS_TEST_CHROME_CHANNEL=chrome` を使います。結果には使用したchannelを出し、配布版Chromiumを試したことにはしません。

## 9. 関門へ接続する

`ci/verify.sh.template` を参照し、案件のverify入口と自動検査へ、禁止パターン、種まき、生成物一致、書き出しのハッシュ・鮮度、実装網羅、再現性、木の照合、期待値の出どころ、数値照合、WebKit、限界報告を接続します。

本番の関門はquickではなく全体検査です。`stage_check.py` で必要な段と終了コードが届いていることを確認します。まだ確認できない段は既存の期限付き宣言で理由を記録し、0件を合格に丸めません。

共通の「共有されているか」は案件外のレジストリを既定で読みません。隣接クローンを使う案件だけ、参照するパスを `--registry` で指定します。

## 10. 公開前にGitを確認する

deployとdeploy:textなど、すべての公開入口の先頭に接続します。

```sh
python3 design/harness/tools/deploy_check.py --root .
```

未コミット・未追跡・確認不能であれば公開を止めます。自動でadd・commit・pushはしません。ビルドが追跡ファイルを書き換える案件は、送信の直前にも確認します。Gitで無視されるビルド出力の正しさは、ビルドと生成物照合が担当します。

## 11. 完了を報告する

検証できた範囲、未解析件数、未検証範囲、実行した試験と失敗、案件への取り込み状況を報告します。共有側の固定具が通っただけで、案件の本番・Figma実データ・iOS実機まで確認済みと報告しません。
