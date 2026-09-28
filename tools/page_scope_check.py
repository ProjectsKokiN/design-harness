#!/usr/bin/env python3
"""参照してよい Figma ページを、フェーズで縛る（2026-08-29 ユーザー確定）。

> Dart によるデザインシステムを作成し、カタログが作成し終わるまで、
> `⚙️_Styles&Components` 以外の Figma ページを参照しない。

**なぜ縛るか。** 画面ページを見ると、AI は部品の仕様を「画面での使われ方」から
推測してしまう。デザインシステムを作る段階で必要なのはコンポーネントの定義であって、
それがどう使われているかではない。推測が入ると、Figma の定義ではなく AI の解釈が
実装に混ざる。既存の実害: 2026-08-07 に Sandbox の無名フレームを実測して
FlashEnglish の画面を実装し、確定 UI と別物になって作り直しになった。

## 3段で守る

1. **宣言** — `design/figma/page-scope.json` に、いまのフェーズと許可ページを書く
2. **構造** — 書き出し器を**許可リスト方式**にする（除外リストではなく）。
   許可ページ以外は書き出しに入らないので、生成物に混ざりようがない
3. **検査（このファイル）** — フェーズに反する記録が残っていないかを見る

## この検査が捕まえるもの

- `phase: design-system` なのに `screens.json` に画面が登録されている
- 同じく `conventions.json` に画面から抽出した規約が入っている
- 書き出しの `$meta` が、許可ページ以外を参照したと記録している

## この検査が捕まえないもの

- **その場かぎりの Figma MCP 呼び出し。** AI が画面ノードを1回読むこと自体は
  止められない（ノードがどのページにあるかは、Figma を呼ばないと分からないため）。
  止められるのは「読んだ結果が記録・生成物に残ること」まで。
  だからこの規則は**宣言と書き出しの許可リストが本体**で、この検査は最後の網
- 確かめた方法: --self-test（フェーズ違反の記録を仕込んで落ちること）

## 使い方

    python3 <harness>/tools/page_scope_check.py --config design/figma/page-scope.json

page-scope.json:

    {
      "phase": "design-system",
      "allowed": ["⚙️_Styles&Components"],
      "reason": "カタログ完成まで画面ページを見ない（使われ方からの推測を防ぐ）",
      "unlockedBy": "Dart のデザインシステムとカタログの完成",
      "screens": "../screens.json",
      "conventions": "../conventions.json",
      "exports": ["../../../design-systems/<名前>/figma/components.json"]
    }

**パスはこのファイルの置き場（`design/figma/`）から書きます。**案件の根から書くと
見つからず、この検査は 2（見ていない）を返します（2026-09-28。それまでは黙って
飛ばして「OK」と言っていました）。

フェーズを `screens` に進めると、画面ページの参照が解禁される。
**進めるのはユーザーの判断**（AI が勝手に進めない）。
"""

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

PHASES = ("design-system", "screens")


#: ページ名らしくない文字（説明が入っている印）
PROSE_MARKS = ("（", "(", "、", "。", " のみ", "です", "ます", "ため")


def _looks_prose(s: str) -> bool:
    """ページ名ではなく説明に見えるか（#35）。

    Figma のページ名は短く、句読点や括弧を持ちません。**長さと印で見ます。**
    """
    return len(s) > 24 or any(m in s for m in PROSE_MARKS)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="参照してよい Figma ページの検査")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.config:
        ap.error("--config が要ります（--self-test を除く）")

    conf = load(args.config)
    if conf is None:
        print(f"設定が読めません: {args.config}", file=sys.stderr)
        return 2
    base = args.config.resolve().parent

    phase = conf.get("phase")
    allowed = conf.get("allowed") or []
    if phase not in PHASES:
        print(f"phase が不正です: {phase!r}（{PHASES} のいずれか）", file=sys.stderr)
        return 2
    if not allowed:
        print("allowed（参照してよいページ）が空です", file=sys.stderr)
        return 2

    print(f"フェーズ: {phase} / 参照してよいページ: {', '.join(allowed)}")
    if conf.get("reason"):
        print(f"  理由: {conf['reason']}")
    if phase == "design-system" and conf.get("unlockedBy"):
        print(f"  解禁の条件: {conf['unlockedBy']}（進めるのはユーザーの判断）")

    # **書いてある参照先が在るかを先に確かめる**（2026-09-28）。それまで「在れば見る・
    # 無ければ黙って飛ばす」だったため、FlashEnglish（5 件）と aub（6 件）では参照先が
    # **1 つも見つからないまま「OK: フェーズの約束どおりです」**と言っていた。ひな形の例が
    # 案件の根から見たパスで書かれていたが、この検査は**このファイルの置き場から**読む
    # （PlantTalk のレジストリの宣言は置き場からのパスで、8 件とも見つかる）。
    unseen = unseen_refs(conf, base)

    problems = []

    if phase == "design-system":
        # 画面を読んだ痕跡が記録に残っていないか
        sp = conf.get("screens")
        if sp and (base / sp).exists():
            doc = load(base / sp) or {}
            n = len(doc.get("sections") or [])
            if n:
                problems.append(
                    f"{sp}: 画面が {n} セクション登録されています。"
                    f"このフェーズでは画面ページを参照しません")
        cp = conf.get("conventions")
        if cp and (base / cp).exists():
            doc = load(base / cp) or {}
            n = len(doc.get("conventions") or [])
            if n:
                problems.append(
                    f"{cp}: 画面から抽出した規約が {n} 件あります。"
                    f"conventions は画面が10枚以上そろってから作ります")

    # 書き出しが許可外ページを参照したと記録していないか
    for ep in conf.get("exports") or []:
        p = base / ep
        if not p.exists():
            continue
        doc = load(p) or {}
        meta = doc.get("$meta", {})
        pages = meta.get("pages") or meta.get("参照したページ")
        if isinstance(pages, str):
            pages = [pages]
        if isinstance(pages, list):
            # **ページ名ではなく説明が入っていないか**（2026-09-04・#35）。
            # qnd-database の実害: `$meta` に散文で書いた説明が、そのまま
            # ページ名として扱われ「許可外のページを参照しています:
            # ["⚙️_Systems のみ（変数とスタイルはファイル単位でページに属さない）"]」
            # で落ちた。既存の案件（414・planttalk）も散文のキーを持っており、
            # `pages` を足すときに同じ書き方をすれば同じところで落ちる。
            prose = [x for x in pages if isinstance(x, str) and _looks_prose(x)]
            if prose:
                problems.append(
                    f"{ep}: `$meta.pages` に**ページ名ではなく説明が入っていませんか**"
                    f"\n      {prose[0][:60]}…"
                    f"\n      `pages` は**ページ名の配列**です。"
                    f"説明は別のキー（`なぜ` など）に書いてください。")
                continue
            extra = [x for x in pages if x not in allowed]
            if extra:
                problems.append(f"{ep}: 許可外のページを参照しています: {extra}")

    if unseen:
        print("\n参照先を読めません。**この検査は、これらを見ていません**:", file=sys.stderr)
        for u in unseen:
            print(f"  - {u}", file=sys.stderr)
    if problems:
        print("\nフェーズの約束に反する状態です:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if unseen:
        # 見たものに反する記録は無いが、見ていないものがある。**「OK」とは言わない**
        return 2
    print("OK: フェーズの約束どおりです。")
    return 0


def _repo_root(start):
    for d in [start, *start.parents]:
        if (d / ".git").exists():
            return d
    return None


def unseen_refs(conf, base):
    """宣言にある参照先（screens / conventions / exports）のうち、読めないものを返す。

    - このファイルの置き場から見て無く、**案件の根から見ると在る** → 書き方の間違い。
      直し方を添えて返す（ひな形の例がこの形だった）
    - exports がどこにも無い → 返す（照合に使ってよい書き出しが無いのは宣言の間違い）
    - screens / conventions がどこにも無い → **まだ作っていない**ことがあるので返さない。
      そのかわり「まだありません」と表示する（黙って飛ばさない）
    """
    root = _repo_root(base)
    where = base.relative_to(root).as_posix() + "/" if root else str(base)
    refs = [(k, conf.get(k)) for k in ("screens", "conventions") if conf.get(k)]
    refs += [("exports", ep) for ep in (conf.get("exports") or [])]
    out = []
    for key, rel in refs:
        if (base / rel).exists():
            continue
        if root and (root / rel).exists():
            out.append(f"{key}: {rel} — 案件の根から見たパスに見えます。"
                       f"このファイルの置き場（{where}）から見たパスに直してください")
        elif key == "exports":
            out.append(f"exports: {rel} — ファイルがありません")
        else:
            print(f"  {key}: {rel} はまだありません（記録は 0 件として扱います）")
    return out


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        def cfg(extra=None):
            d = {"phase": "design-system", "allowed": ["⚙️_Styles&Components"],
                 "screens": "screens.json", "conventions": "conventions.json",
                 "exports": ["export.json"]}
            d.update(extra or {})
            (base / "c.json").write_text(json.dumps(d, ensure_ascii=False),
                                         encoding="utf-8")
            return ["--config", str(base / "c.json")]

        (base / "screens.json").write_text('{"sections": []}', encoding="utf-8")
        (base / "conventions.json").write_text('{"conventions": []}', encoding="utf-8")
        (base / "export.json").write_text(
            '{"$meta": {"pages": ["⚙️_Styles&Components"]}}', encoding="utf-8")
        if main(cfg()) != 0:
            print("self-test NG: 約束どおりなのに落ちた"); ok = False

        (base / "screens.json").write_text('{"sections": [{"name": "Home"}]}',
                                           encoding="utf-8")
        if main(cfg()) != 1:
            print("self-test NG: 画面が登録されていても落ちなかった"); ok = False
        (base / "screens.json").write_text('{"sections": []}', encoding="utf-8")

        (base / "export.json").write_text(
            '{"$meta": {"pages": ["⚙️_Styles&Components", "🎨_AppDesign"]}}',
            encoding="utf-8")
        if main(cfg()) != 1:
            print("self-test NG: 許可外ページの参照で落ちなかった"); ok = False
        (base / "export.json").write_text(
            '{"$meta": {"pages": ["⚙️_Styles&Components"]}}', encoding="utf-8")

        # フェーズを進めれば画面の登録は許される
        (base / "screens.json").write_text('{"sections": [{"name": "Home"}]}',
                                           encoding="utf-8")
        if main(cfg({"phase": "screens"})) != 0:
            print("self-test NG: screens フェーズで画面が許されなかった"); ok = False

    # ─── 参照先が読めないときに「OK」と言わない（2026-09-28）──────────────
    # FlashEnglish と aub は、ひな形の例どおり案件の根から見たパスで書いていたため、
    # 参照先が 1 つも見つからないまま「OK」になっていた
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir()
        fig = root / "design" / "figma"
        fig.mkdir(parents=True)
        (root / "design" / "screens.json").write_text('{"sections": []}', encoding="utf-8")
        (root / "export.json").write_text('{"$meta": {"pages": ["P"]}}', encoding="utf-8")

        def run(d):
            (fig / "page-scope.json").write_text(json.dumps(d), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--config", str(fig / "page-scope.json")])
            return rc, err.getvalue()
        base_d = {"phase": "design-system", "allowed": ["P"]}
        rc, err = run({**base_d, "screens": "design/screens.json"})
        if rc != 2 or "案件の根から見たパス" not in err:
            print(f"self-test NG: 案件の根から書いた参照先で OK と言った（rc={rc}）"); ok = False
        rc, err = run({**base_d, "screens": "../screens.json", "exports": ["../../export.json"]})
        if rc != 0:
            print(f"self-test NG: 置き場から書いた参照先で落ちた（rc={rc}）{err}"); ok = False
        rc, err = run({**base_d, "exports": ["../../ない.json"]})
        if rc != 2 or "ファイルがありません" not in err:
            print(f"self-test NG: 無い書き出しで OK と言った（rc={rc}）"); ok = False
        rc, err = run({**base_d, "screens": "../まだ無い.json"})
        if rc != 0:
            print(f"self-test NG: まだ作っていない記録で落ちた（rc={rc}）"); ok = False
        # 見ていないものと、見たものの違反が両方あれば 1（2 に薄めない）
        (root / "bad.json").write_text('{"$meta": {"pages": ["Q"]}}', encoding="utf-8")
        rc, err = run({**base_d, "exports": ["../../bad.json", "design/ない.json"]})
        if rc != 1:
            print(f"self-test NG: 違反と見ていないものが両方あるのに 1 でない（rc={rc}）"); ok = False

    # ─── #35: 散文をページ名として扱わない ─────────────────────────
    for s, want in (
        ("⚙️_Systems のみ（変数とスタイルはファイル単位でページに属さない）", True),
        ("参照しないページ", False),
        ("⚙️_Styles&Components", False),
        ("🎨_AppDesign", False),
        ("Page 1", False),
        ("下書き、AI出力", True),
        ("このページだけを見ます。", True),
        ("とても長い名前がずっと続くページの名前でページ名には見えないもの", True),
    ):
        got = _looks_prose(s)
        if got != want:
            print(f"self-test NG: 散文の見分けが違う: {s!r} → {got}（期待 {want}）")
            ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
