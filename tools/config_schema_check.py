#!/usr/bin/env python3
"""**設定ファイルの鍵と型だけ**を見る（design-harness #126・2026-09-19 新設）。

## なぜ要るか

**「確かめられなかった」の段は、設定の中身が正しいことを何も保証していません。**

planttalk-ios（2026-09-19）で、`design/gaps.json` の `notVerifiable` が
`item` / `why` / `reviewBy` ではなく**日本語の鍵**（項目・理由・棚卸し日）で
書かれていました。`gap_report.py` はこれを落としますが、**走査対象が0件のあいだは
段そのものが「確かめられなかった」で止まり、書式まで見ていませんでした。**

**案件の立ち上げ時に書いた宣言が、実装が入る何週間も後まで検査されません。**
同じ日に `stages.json` の `notHere` の理由も古くなっていました。

## この道具の立ち位置

**走査対象が0件でも回ります。**中身の正しさ（理由が妥当か・期限が適切か）は
見ません。**鍵の名前と型だけ**を見ます。

## 終了コード

  0 … 見た設定ファイルの鍵と型が全部正しい
  1 … 鍵の名前か型が違う
  2 … 確かめられなかった（設定ファイルが1つも無い・JSON が壊れている）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

# 宣言のかたまりごとに「要る鍵」を決める。**ここが正本。**
# 値は (要る鍵, かたまりの型) で、型は "listOfDict"（一覧）か "dictOfDict"（名前つき）
BLOCKS = {
    "gaps.json": {
        "notVerifiable": (("item", "why", "reviewBy"), "listOfDict"),
    },
    "stages.json": {
        "notHere":      (("why", "reviewBy"), "dictOfDict"),
        "外した":        (("why", "かわりに", "reviewBy"), "dictOfDict"),
        "まだ測れない":   (("why", "reviewBy"), "dictOfDict"),
        "緩和":          (("what", "why", "reviewBy"), "listOfDict"),
    },
    "machine-scope.json": {
        "machines": ((), "dictOfAny"),
    },
    "rules.json": {
        "rules": (("id",), "listOfDict"),
    },
}

# **その設定ファイルに必ず要るトップレベルの鍵**（無いと段が空回りする）
REQUIRED_TOP = {
    "machine-scope.json": ("machines",),
    "rules.json": ("rules",),
}


def check_file(path: Path) -> tuple[int, list[str]]:
    """(見た数, 誤りの行) を返す。"""
    name = path.name
    blocks = BLOCKS.get(name)
    if blocks is None:
        return 0, []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return 0, [f"  **JSON が壊れています**: {path} — {e}"]
    if not isinstance(data, dict):
        return 0, [f"  **いちばん外が辞書ではありません**: {path}"]

    errs, seen = [], 0
    for key in REQUIRED_TOP.get(name, ()):
        if key not in data:
            errs.append(f"  **`{key}` がありません**: {path}")

    for key, (needed, kind) in blocks.items():
        if key not in data:
            continue          # 宣言そのものが無いのは正しい状態
        seen += 1
        v = data[key]
        if kind == "listOfDict":
            if not isinstance(v, list):
                errs.append(f"  **`{key}` は一覧（配列）で書いてください**: {path}"
                            f"（いまは {type(v).__name__}）")
                continue
            for i, item in enumerate(v):
                if not isinstance(item, dict):
                    errs.append(f"  `{key}[{i}]` が辞書ではありません: {path}")
                    continue
                miss = [k for k in needed if not str(item.get(k, "")).strip()]
                if miss:
                    errs.append(
                        f"  **`{key}[{i}]` に {'・'.join(miss)} がありません**: {path}\n"
                        f"      いまの鍵: {list(item)}\n"
                        f"      **日本語の鍵で書いていませんか。**要る鍵は {'・'.join(needed)} です")
        elif kind == "dictOfDict":
            if not isinstance(v, dict):
                errs.append(f"  **`{key}` は名前つきの辞書で書いてください**: {path}"
                            f"（いまは {type(v).__name__}）")
                continue
            for k2, item in v.items():
                if not isinstance(item, dict):
                    errs.append(f"  `{key}.{k2}` が辞書ではありません: {path}")
                    continue
                miss = [k for k in needed if not str(item.get(k, "")).strip()]
                if miss:
                    errs.append(
                        f"  **`{key}.{k2}` に {'・'.join(miss)} がありません**: {path}\n"
                        f"      いまの鍵: {list(item)} / 要る鍵: {'・'.join(needed)}")
        elif kind == "dictOfAny":
            if not isinstance(v, dict):
                errs.append(f"  **`{key}` は辞書で書いてください**: {path}"
                            f"（いまは {type(v).__name__}）")
    return seen, errs


def run(paths: list[Path]) -> int:
    files = [p for p in paths if p.is_file()]
    if not files:
        print("設定ファイルが1つもありません。**0件は「綺麗」ではなく「見ていない」です**")
        return 2
    total_blocks, errs, looked = 0, [], []
    for p in files:
        n, e = check_file(p)
        total_blocks += n
        errs += e
        if p.name in BLOCKS:
            looked.append(f"{p.name}({n})")
    if not looked:
        print(f"見方を知っている設定ファイルがありません（渡された {len(files)} 件）")
        return 2
    for l in errs:
        print(l)
    tail = f"設定 {len(looked)} ファイル / 宣言のかたまり {total_blocks} 件を見ました（{', '.join(looked)}）"
    if errs:
        print(f"NG: {tail}。**鍵の名前か型が違います。**")
        return 1
    print(f"OK: {tail}")
    return 0


def self_test() -> int:
    import contextlib, io, tempfile
    bad = []

    def case(name, got, want):
        if got != want:
            bad.append(f"{name}: {want} のはずが {got}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        root = Path(d)

        def go(fname, obj):
            p = root / fname
            p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run([p])
            return rc, buf.getvalue()

        ok_item = {"item": "ぼかし", "why": "描画結果でしか見えない", "reviewBy": "2026-11-30"}
        case("正しい gaps", go("gaps.json", {"notVerifiable": [ok_item]})[0], 0)

        # **これが実際に起きた形**（日本語の鍵）
        rc, out = go("gaps.json", {"notVerifiable": [
            {"項目": "ぼかし", "理由": "x", "棚卸し日": "2026-11-30"}]})
        case("日本語の鍵を捕まえる", rc, 1)
        if "日本語の鍵で書いていませんか" not in out:
            bad.append("日本語の鍵だと気づける文言が出ていない")

        case("宣言が無いのは正しい", go("gaps.json", {"rules": "x"})[0], 0)
        case("一覧でなければ落ちる",
             go("gaps.json", {"notVerifiable": {"a": ok_item}})[0], 1)
        case("stages の 外した は かわりに が要る",
             go("stages.json", {"外した": {"a": {"why": "x", "reviewBy": "2026-11-30"}}})[0], 1)
        case("stages の 外した が揃えば通る",
             go("stages.json", {"外した": {"a": {"why": "x", "かわりに": "y",
                                                "reviewBy": "2026-11-30"}}})[0], 0)
        case("まだ測れない も見る",
             go("stages.json", {"まだ測れない": {"a": {"why": "x"}}})[0], 1)
        case("machines が無い machine-scope は落ちる",
             go("machine-scope.json", {"shared": []})[0], 1)
        case("rules が無い rules.json は落ちる",
             go("rules.json", {"version": 1})[0], 1)
        case("id の無いルールは落ちる",
             go("rules.json", {"rules": [{"pattern": "x"}]})[0], 1)
        def quiet(fn):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                return fn()

        (root / "gaps.json").write_text("{壊れ", encoding="utf-8")
        case("壊れた JSON は落ちる（2 ではなく 1）",
             quiet(lambda: run([root / "gaps.json"])), 1)
        case("設定が無ければ 2", quiet(lambda: run([root / "無い.json"])), 2)

    if bad:
        for b in bad:
            print(b)
        print(f"NG: 自己検査が {len(bad)} 件落ちました。**この道具が空振りしています。**")
        return 1
    print("OK: 自己検査 12 件とも期待どおりでした")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="設定ファイルの鍵と型だけを見る")
    ap.add_argument("paths", nargs="*", type=Path, help="設定ファイル（既定は design/ の4つ）")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    paths = a.paths or [a.root / "design" / n for n in BLOCKS]
    return run(paths)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # mutation-ok: 例外の帰り道。中からは通せない
        print(f"例外で止まりました: {e}")
        sys.exit(2)
