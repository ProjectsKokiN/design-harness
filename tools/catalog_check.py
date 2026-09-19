#!/usr/bin/env python3
"""**自作部品が、人の目で見られる場所に出ているか**を見る（2026-09-20 新設）。

## なぜ要るか

PlantTalk を Flutter から SwiftUI へ移したとき、**画面 3 枚が 2 回作り直し**に
なりました。Flutter 版でそこまでずれなかった歯止めは 2 つあり、そのうち 1 つが
**ブラウザで部品を 1 枚ずつ見せていたこと**（`lib/preview/main.dart`）でした。
**移すときにこれが落ちました。**落ちたことを、どの段も言いませんでした。

`#Preview` は歯止めになりません。**Xcode が要ります。**UI を作る機体
（MacBook Air）に Xcode が無いので、作った本人が見られません。
見てもらう相手も実機か Simulator で見ます。**そこに出ないものは歯止めではない。**

## 何を分母にするか

**手で書かないこと。**書き出し（`figma/components.json`）の各セットの判定欄が
そのまま使えます。PlantTalk の例:

    Chips/Plain   実装='実装する'                              → 対象
    Icon          実装='**実装しない（Image(systemName:) に…）' → 対象外
    Lists         実装='**実装しない**'                         → 対象外

Apple のキット部品はそもそも `componentSets` に入りません（ページの範囲で
ライブラリを照合の対象外に宣言しているため）。**「iOS に標準搭載されている
ものは作らない」は、これで機械が判定できます**（2026-09-20 ユーザー確定）。

分母を数字で書くと、宣言と実数がずれても誰も落ちません。PlantTalk では
`tokens.json` の Spacing が Figma と 1 段ずれ、**誤った値が実装 4 箇所まで
届いていました。**同じ轍を踏まないため、ここでは数を書きません。

## 何を落とすか

**実装済みの対象が、カタログに出ていなければ落とします。**
未実装のものは条件7（実装網羅）が別に数えているので、ここでは二重に見ません。
**実装したのにカタログへ足し忘れた瞬間**に落ちるのが、この段の目的です。

## 終了コード

    0 … 確かめて合格
    1 … 確かめて違反（実装済みなのにカタログに無い）
    2 … **確かめられなかった**（書き出しが無い・設定が無い・分母が 0 件）

**0 件は「綺麗」ではなく「見ていない」**なので 2 を返します。

## 設定（案件の design/catalog.json）

    {
      "export": "../design-systems/<名前>/figma/components.json",
      "catalog": "Sources/<名前>/Catalog/CatalogView.swift",
      "impl_roots": ["Sources/<名前>/Catalog"],
      "作る判定": {"キー": "実装", "作る値": "実装する"},
      "対象外": {"<セット名>": "理由"}
    }

`対象外` は**書き出しが「実装する」と言っているのに、この案件では出さない**ものを
理由つきで宣言する逃げ道です。**空で置くこと。**埋めるときは理由を書きます。
"""
import json
import re
import sys
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def targets(export: dict, key: str, want: str):
    """書き出しから「作る」と宣言されているセット名を返す。"""
    sets = export.get("componentSets") or {}
    out = []
    for name, v in sets.items():
        if not isinstance(v, dict):
            continue
        val = str(v.get(key, ""))
        # **「実装しない」を先に見る。**「実装する」は「実装しない」の部分文字列ではないが、
        # 強調の `**` が付いた形（`**実装しない**`）や註釈つきの形があるため、
        # 含むかどうかではなく**否定を先に落とす**
        if "しない" in val:
            continue
        if want in val:
            out.append(name)
    return out


def implemented(export: dict, names, roots):
    """対象のうち、実装が実在するものだけを返す。

    `swiftView` の名前が実装ファイル群のどこかに `struct <名前>` として
    在るかで見る。**文字が入っているだけでは実装ありにしない**
    （PlantTalk で、改名後に対応表だけ残って空振りの緑になった実害がある）。
    """
    files = []
    for r in roots:
        p = Path(r)
        if p.is_dir():
            files += [f for f in p.rglob("*.swift")]
        elif p.is_file():
            files.append(p)
    blob = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
    got = []
    for n in names:
        view = (export["componentSets"][n] or {}).get("swiftView") or ""
        view = re.split(r"[（(]", str(view))[0].strip()
        if view and view not in ("—", "-") and re.search(rf"\bstruct\s+{re.escape(view)}\b", blob):
            got.append((n, view))
    return got


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv or "--selftest" in argv:
        return self_test()
    if "--config" not in argv:
        print("--config <案件>/design/catalog.json を渡してください", file=sys.stderr)
        return 2
    cfg_path = Path(argv[argv.index("--config") + 1])
    if not cfg_path.exists():
        print(f"設定がありません: {cfg_path}", file=sys.stderr)
        print("  **置いていないことと、対象 0 件は別です。**", file=sys.stderr)
        return 2
    cfg = load(cfg_path)
    base = cfg_path.resolve().parent.parent

    exp_path = (base / cfg["export"]).resolve()
    if not exp_path.exists():
        print(f"書き出しがありません: {exp_path}", file=sys.stderr)
        print("  **分母が取れないので、通しません。**", file=sys.stderr)
        return 2
    export = load(exp_path)

    rule = cfg.get("作る判定") or {}
    names = targets(export, rule.get("キー", "実装"), rule.get("作る値", "実装する"))
    skip = cfg.get("対象外") or {}
    names = [n for n in names if n not in skip]
    if not names:
        print("**作ると宣言された部品が 1 件もありません。**", file=sys.stderr)
        print(f"  書き出し: {exp_path}", file=sys.stderr)
        print("  判定欄の書き方が変わった可能性があります。"
              "**0 件は『綺麗』ではなく『見ていない』です。**", file=sys.stderr)
        return 2

    roots = [base / r for r in (cfg.get("impl_roots") or [])]
    done = implemented(export, names, roots)

    cat_path = base / cfg["catalog"]
    if not cat_path.exists():
        print(f"カタログがありません: {cat_path}", file=sys.stderr)
        print(f"  作ると宣言された部品 {len(names)} 件 / 実装済み {len(done)} 件。"
              f"**見る場所がありません。**", file=sys.stderr)
        return 1 if done else 2
    cat = cat_path.read_text(encoding="utf-8", errors="replace")

    missing = [(n, v) for n, v in done if f'"{n}"' not in cat]
    print(f"部品カタログ: 作ると宣言 {len(names)} 件 / 実装済み {len(done)} 件 / "
          f"カタログに出ている {len(done) - len(missing)} 件"
          + (f" / 宣言して外した {len(skip)} 件" if skip else ""))
    for n, why in skip.items():
        print(f"  外した: {n} — {why}")
    if missing:
        print("\n**実装したのにカタログに出ていない部品があります:**", file=sys.stderr)
        for n, v in missing:
            print(f"  - {n}（{v}）", file=sys.stderr)
        print(f"  {cat_path} に足してください。"
              f"**セット名を文字列でそのまま書く**と、この検査が見つけます。", file=sys.stderr)
        return 1
    not_yet = [n for n, _ in [(n, None) for n in names] if n not in [d[0] for d in done]]
    if not_yet:
        print(f"  まだ実装していない（条件7 が別に数えます）: {', '.join(not_yet)}")
    return 0


def self_test() -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "design").mkdir()
        (base / "reg").mkdir()
        (base / "src").mkdir()
        exp = {"componentSets": {
            "Chips/Plain": {"実装": "実装する", "swiftView": "Chip"},
            "Toast": {"実装": "実装する", "swiftView": "Toast"},
            "Icon": {"実装": "**実装しない（Image(systemName:) に置き換える）**", "swiftView": "—"},
            "Lists": {"実装": "**実装しない**", "swiftView": "—"},
            # **決定がひっくり返った跡が残っている形。**「実装する」という字を
            # 含んだまま「実装しない」と書かれる。含むかどうかだけで判定すると
            # **数えてしまう。**否定を先に落とす必要がある。
            # 実装名（Divider）が実在するので、数えると「カタログに無い」で落ちる
            "Separator": {"実装": "実装する予定だったが、**実装しない**（SwiftUI の Divider）",
                          "swiftView": "Divider"},
        }}
        (base / "reg" / "components.json").write_text(json.dumps(exp, ensure_ascii=False),
                                                      encoding="utf-8")
        (base / "src" / "Chip.swift").write_text("struct Chip: View {}\n", encoding="utf-8")
        (base / "src" / "Divider.swift").write_text("struct Divider: View {}\n", encoding="utf-8")
        cfg = {"export": "reg/components.json", "catalog": "src/CatalogView.swift",
               "impl_roots": ["src"], "作る判定": {"キー": "実装", "作る値": "実装する"},
               "対象外": {}}
        cfgp = base / "design" / "catalog.json"

        def write_cfg(c=None):
            cfgp.write_text(json.dumps(c or cfg, ensure_ascii=False), encoding="utf-8")

        def run():
            return main(["--config", str(cfgp)])

        cat = base / "src" / "CatalogView.swift"
        write_cfg()

        # **実装済みなのにカタログが無ければ 1**
        if run() != 1:
            print("self-test NG: カタログが無いのに通しました"); ok = False

        # **カタログに載っていなければ 1**
        cat.write_text("// からっぽ\n", encoding="utf-8")
        if run() != 1:
            print("self-test NG: 載っていないのに通しました"); ok = False

        # **載っていれば 0。未実装（Toast）は落とさない**
        cat.write_text('let entries = ["Chips/Plain"]\n', encoding="utf-8")
        if run() != 0:
            print("self-test NG: 載っているのに落ちました"); ok = False

        # **実装したのに足し忘れたら落ちる**（この段の目的）
        (base / "src" / "Toast.swift").write_text("struct Toast: View {}\n", encoding="utf-8")
        if run() != 1:
            print("self-test NG: **実装したのに足し忘れたのを見逃しました**"); ok = False
        cat.write_text('let entries = ["Chips/Plain", "Toast"]\n', encoding="utf-8")
        if run() != 0:
            print("self-test NG: 両方載せたのに落ちました"); ok = False

        # **「実装しない」を対象にしない。**Separator は実装名（Divider）を持ち、
        # その struct も実在するので、数えてしまうと「カタログに無い」で落ちる
        cat.write_text('let entries = ["Chips/Plain", "Toast"]\n', encoding="utf-8")
        if run() != 0:
            print("self-test NG: **実装しないものを数えました**"); ok = False

        # **書き出しが無ければ 2**
        c2 = dict(cfg); c2["export"] = "reg/nope.json"; write_cfg(c2)
        if run() != 2:
            print("self-test NG: 書き出しが無いのに 2 を返しませんでした"); ok = False

        # **判定欄の書き方が変わって 0 件になったら 2**（「綺麗」ではなく「見ていない」）
        c3 = dict(cfg); c3["作る判定"] = {"キー": "実装", "作る値": "つくる"}; write_cfg(c3)
        if run() != 2:
            print("self-test NG: **対象 0 件を通しました**（見ていないのに緑）"); ok = False

        # **設定が無ければ 2**
        cfgp.unlink()
        if run() != 2:
            print("self-test NG: 設定が無いのに 2 を返しませんでした"); ok = False

    print("self-test: " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
