#!/usr/bin/env python3
"""**デザイナー本人が見た画面の割合**を数える（候補10・2026-11-03）。

「見た目の評価はデザイナー本人」と決めていても、**本人の目がどこまで届いているかは誰も数えていなかった。**
外部の実践例（note: minto_tokyo「セキュリティ思考で作る、1人デザイナーのデザインハーネス」の
デザインカバレッジ。255画面中73）から取り入れた。

## 記録の仕方（2026-11-03 ユーザー確定）

> **画面が見た記録は私があなたに言うので、それが記録になると思います。**

デザイナーが会話で「○○の画面を見た」と言ったら、AI が `--record <画面> --note "<本人の言葉>"` を回す。
記録には、そのときの**実装ファイルのハッシュ**を残す。**見た目に関わるファイルが後で変わったら、
その画面は「未判断」に戻る**（situations_check の「ハッシュが動いたら再確認」と同じ作り）。

## 設定（`design/design-coverage.json`）

    {"screens": [{"name": "ResetDataSheet", "impl": ["lib/ui/reset_data_sheet.dart"]}, ...],
     "log": "design/design-reviews.jsonl"}

`impl` はその画面の見た目を決めるファイル（glob 可）。**画面の一覧は手で写さず、案件の画面一覧から作る**
（FlashEnglish の screens.json の impl など）。

## 終了コード

    0  数えた（割合は報せ。--min を付けたときだけ下回ると 1）
    1  --min を下回った
    2  確かめられなかった（設定が無い・画面が0・実装のファイルが無い画面がある）
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401


def impl_files(root, patterns):
    out = []
    for pat in patterns:
        out += sorted(Path(x) for x in glob.glob(str(root / pat), recursive=True) if Path(x).is_file())
    return out


def digest(root, patterns):
    files = impl_files(root, patterns)
    if not files:
        return None, {}
    each = {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    whole = hashlib.sha256(json.dumps(each, sort_keys=True).encode("utf-8")).hexdigest()
    return whole, each


def load(cfg_path):
    conf = json.loads(cfg_path.read_text(encoding="utf-8"))
    screens = conf.get("screens") or []
    if not isinstance(screens, list):
        raise ValueError("screens は一覧で書いてください")
    return conf, screens


def read_log(path):
    recs = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                recs.append(json.loads(line))
    return recs


def churn(root, patterns, days=90):
    """直近の変更回数（git log）。読めなければ 0。"""
    files = [f.relative_to(root).as_posix() for f in impl_files(root, patterns)]
    if not files:
        return 0
    try:
        r = subprocess.run(["git", "-C", str(root), "log", f"--since={days}.days", "--format=%H", "--", *files],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return len([x for x in r.stdout.splitlines() if x.strip()]) if r.returncode == 0 else 0
    except (OSError, subprocess.SubprocessError):
        return 0


def report(cfg_path, root, min_pct=None):
    try:
        conf, screens = load(cfg_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return 2, [f"設定が読めません: {cfg_path}: {e}"]
    if not screens:
        return 2, ["**画面が1つもありません。**分母が無いので数えられません"]
    log = root / conf.get("log", "design/design-reviews.jsonl")
    latest = {}
    for r in read_log(log):
        latest[r.get("screen")] = r
    seen, back, never, missing = [], [], [], []
    for s in screens:
        whole, _ = digest(root, s.get("impl") or [])
        if whole is None:
            missing.append(s["name"])
            continue
        r = latest.get(s["name"])
        if not r:
            never.append(s)
        elif r.get("digest") != whole:
            back.append((s, r))
        else:
            seen.append((s, r))
    if missing:
        return 2, [f"**実装のファイルが見つからない画面があります**（数えられません）: {', '.join(missing)}"]
    n = len(screens)
    pct = round(100 * len(seen) / n, 1)
    lines = [f"デザイナーが見た画面: {len(seen)} / {n}（{pct}%）・見た後に変わった {len(back)}・一度も見ていない {len(never)}"]
    for s, r in back:
        lines.append(f"  未判断に戻った: {s['name']}（{r.get('at', '?')} に見た後、見た目のファイルが変わった）")
    todo = sorted(never + [s for s, _ in back], key=lambda s: -churn(root, s.get("impl") or []))
    if todo:
        lines.append("  次に見てもらう候補（直近90日の変更が多い順）: " + "、".join(s["name"] for s in todo[:3]))
    if min_pct is not None and pct < min_pct:
        lines.append(f"**下限 {min_pct}% を下回っています。**")
        return 1, lines
    return 0, lines


def record(cfg_path, root, screen, note, when=None):
    conf, screens = load(cfg_path)
    s = next((x for x in screens if x.get("name") == screen), None)
    if not s:
        return 2, [f"その名前の画面がありません: {screen}（設定の screens: {', '.join(x['name'] for x in screens)}）"]
    whole, each = digest(root, s.get("impl") or [])
    if whole is None:
        return 2, [f"実装のファイルが見つかりません: {screen}"]
    if not str(note or "").strip():
        return 2, ["**本人の言葉（--note）がありません。**記録は本人が見たことの証拠なので、言葉のまま残します"]
    log = root / conf.get("log", "design/design-reviews.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    rec = {"screen": screen, "at": (when or dt.date.today()).isoformat(), "by": "designer",
           "note": note, "digest": whole, "files": each}
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0, [f"記録しました: {screen}（{rec['at']}・ファイル {len(each)} 本）"]


def self_test():
    import tempfile
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "lib").mkdir()
        (root / "design").mkdir()
        (root / "lib" / "a.dart").write_text("A", encoding="utf-8")
        (root / "lib" / "b.dart").write_text("B", encoding="utf-8")
        cfg = root / "design" / "design-coverage.json"
        cfg.write_text(json.dumps({"screens": [{"name": "A", "impl": ["lib/a.dart"]},
                                               {"name": "B", "impl": ["lib/b.dart"]}]}), encoding="utf-8")
        rc, out = report(cfg, root)
        ck(rc == 0 and "0 / 2" in out[0], f"何も見ていないのに 0/2 と言わない: {out}")
        rc, out = record(cfg, root, "A", "A の画面、見ました。大丈夫です", dt.date(2026, 11, 3))
        ck(rc == 0, f"記録できない: {out}")
        rc, out = report(cfg, root)
        ck("1 / 2" in out[0] and "50.0%" in out[0], f"見た画面を数えていない: {out}")
        (root / "lib" / "a.dart").write_text("A2", encoding="utf-8")
        rc, out = report(cfg, root)
        ck("0 / 2" in out[0] and any("未判断に戻った: A" in x for x in out),
           f"**見た後にファイルが変わったのに、見たままにしている**: {out}")
        ck(any("次に見てもらう候補" in x for x in out), f"候補を出さない: {out}")
        rc, out = report(cfg, root, min_pct=50)
        ck(rc == 1, f"下限を下回ったのに 1 でない: {rc}")
        rc, out = record(cfg, root, "Z", "見た")
        ck(rc == 2, f"無い画面を記録した: {rc}")
        rc, out = record(cfg, root, "B", "")
        ck(rc == 2, f"本人の言葉が無いのに記録した: {rc}")
        cfg.write_text(json.dumps({"screens": [{"name": "C", "impl": ["lib/none.dart"]}]}), encoding="utf-8")
        rc, _ = report(cfg, root)
        ck(rc == 2, f"実装のファイルが無い画面を数えた: {rc}")
        cfg.write_text(json.dumps({"screens": []}), encoding="utf-8")
        rc, _ = report(cfg, root)
        ck(rc == 2, f"画面0なのに 2 でない: {rc}")
        cfg.write_text(json.dumps({"screens": [{"name": "A", "impl": ["lib/a.dart"]}]}), encoding="utf-8")
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ck(main(["--config", str(cfg), "--root", str(root), "--record", "A", "--note", "見た"]) == 0, "入口で記録できない")
            ck(main(["--config", str(cfg), "--root", str(root)]) == 0, "入口で数えられない")
            ck(main(["--config", str(cfg), "--root", str(root), "--min", "100"]) == 0, "全部見たのに下限で落ちた")
            (root / "lib" / "a.dart").write_text("A3", encoding="utf-8")
            ck(main(["--config", str(cfg), "--root", str(root), "--min", "100"]) == 1, "入口が下限で 1 を返さない")
            ck(main(["--config", str(root / "none.json"), "--root", str(root)]) == 2, "設定が無いのに 2 でない")
            cfg.write_text(json.dumps({"screens": []}), encoding="utf-8")
            ck(main(["--config", str(cfg), "--root", str(root)]) == 2, "入口が画面0で 2 を返さない")

    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="デザイナー本人が見た画面の割合を数える")
    ap.add_argument("--config", type=Path, default=Path("design/design-coverage.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--record", metavar="画面", help="本人が見たと言った画面を記録する")
    ap.add_argument("--note", help="本人の言葉（原文のまま）")
    ap.add_argument("--min", type=float, help="この割合（%）を下回ったら 1")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.config.is_file():
        print(f"設定がありません: {a.config}。見た画面を数えられません", file=sys.stderr)
        return 2
    root = a.root.resolve()
    if a.record:
        rc, lines = record(a.config, root, a.record, a.note)
    else:
        rc, lines = report(a.config, root, a.min)
    for x in lines:
        print(x, file=sys.stderr if rc else sys.stdout)
    if rc == 2:
        return 2
    if rc != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
