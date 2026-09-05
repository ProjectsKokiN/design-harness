#!/usr/bin/env python3
"""書き出しの中身の指紋（`$meta.payloadDigest`）を、**一覧を持たずに全部**照合する（2026-09-05 新設・#66）。

## なぜ要るか

書き出しの `$meta` には指紋がある。意味はファイル自身にこう書いてある。

> **Figma から書き出したものを、そのまま写せているかの証明。**

ところが照合する道具は案件ローカルで、**対象が手書きの一覧**（21ファイル）だった。
画面まわりの書き出し5件は**後から足した日に一覧への追加を忘れ**、忘れたことは誰にも
分からなかった——指紋は書いてあるので、見た目は揃っている。
結果、`screen_chrome_layout.json` の指紋が**丸1日古いまま通った**。

**一覧を持たない。** `design/figma/*.json` を全部歩き、`$meta.payloadDigest` を持つものは
全部照合する。持たないものは「照合できない」と**名指しで出す**（飾りの指紋を見つけるため）。

## 式（aub の `design/gen/digests.py` と同じ。ここが正本になる）

    payload = $meta を除いた中身
    body    = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    value   = FNV-1a 32bit（ord(ch) & 0xFF・シフトの形。JS 側と値を揃えるため）

## 使い方（案件のルートで）

    python3 tools/digest_check.py [--dir design/figma] [--allow-missing frames.json ...]

捕まえないもの: 中身が Figma と合っているか（鮮度の段）。ここは「写した後に手直ししていないか」だけ
確かめた方法: --self-test（中身を1字変えると落ちること・指紋の無い書き出しを名指しすること）
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


def fnv1a(body: str) -> int:
    """FNV-1a 32bit。**乗算で書かない**（JS 側で 2^53 を超えて値が合わなくなる）。"""
    h = 0x811C9DC5
    for ch in body:
        h ^= ord(ch) & 0xFF
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) & 0xFFFFFFFF
    return h


def payload_digest(doc: dict) -> dict:
    payload = {k: v for k, v in doc.items() if k != "$meta"}
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"algo": "FNV-1a 32bit", "rows": len(payload), "chars": len(body), "value": fnv1a(body)}


def check_dir(d: Path, allow_missing=()):
    """(照合した, ずれた, 指紋の無い) を返す。"""
    files = sorted(p for p in d.glob("*.json") if p.is_file())
    checked, bad, missing = [], [], []
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            bad.append(f"  {f.name}: 読めません（{e}）")
            continue
        if not isinstance(doc, dict):
            continue
        meta = doc.get("$meta") or {}
        want = meta.get("payloadDigest")
        if not isinstance(want, dict) or "value" not in want:
            if f.name not in allow_missing:
                missing.append(f.name)
            continue
        got = payload_digest(doc)
        if got["value"] != want.get("value") or got["chars"] != want.get("chars"):
            bad.append(f"  {f.name}: 指紋がずれています（記録 {want.get('value')} / "
                       f"いま {got['value']}・文字数 {want.get('chars')} → {got['chars']}）。\n"
                       f"    **写した後に手で直したか、取り直したのに $meta を更新していません。**")
        else:
            checked.append(f.name)
    return checked, bad, missing, len(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description="書き出しの中身の指紋を全部照合する")
    ap.add_argument("--dir", type=Path, default=Path("design/figma"))
    ap.add_argument("--allow-missing", nargs="*", default=[],
                    help="指紋を持たなくてよい書き出し（手書きの宣言など）。理由は exporters.json の allow に")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.dir.exists():
        print(f"書き出しの置き場がありません: {args.dir}", file=sys.stderr)
        return 2
    checked, bad, missing, total = check_dir(args.dir, set(args.allow_missing))
    if total == 0:
        print(f"書き出しが1件もありません: {args.dir}。**0件は「綺麗」ではなく「見ていない」です。**",
              file=sys.stderr)
        return 2
    if bad:
        print(f"書き出しの指紋がずれています（{len(bad)}/{total} 件）:", file=sys.stderr)
        print("\n".join(bad), file=sys.stderr)
        return 1
    if missing:
        # 指紋が無いのは落とさない（手書きの宣言は器を持たない）。**ただし必ず名指しする**
        print(f"注意: 指紋（payloadDigest）を持たない書き出し {len(missing)} 件: "
              + " / ".join(missing) + "\n"
              f"  器が作ったものなら $meta.payloadDigest を持たせてください。"
              f"手書きの宣言なら --allow-missing に理由つきで。**飾りの指紋（式の無い digest）はここに出ます**")
    print(f"書き出しの指紋: {len(checked)}/{total} 件を照合、すべて一致（一覧は持たない。全部歩いた）")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "design" / "figma"; d.mkdir(parents=True)
        doc = {"$meta": {"unit": "x"}, "sets": {"A": {"w": 1}}}
        doc["$meta"]["payloadDigest"] = payload_digest(doc)
        (d / "a.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

        def run(*extra):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--dir", str(d), *extra])
            return rc, buf.getvalue()

        rc, out = run()
        if rc != 0 or "1/1 件を照合" not in out:
            print(f"self-test NG: 一致しているのに落ちた（{rc}）\n   {out[:200]}"); ok = False
        # **中身を1字変えると落ちる**（写した後の手直し）
        doc2 = json.loads(json.dumps(doc)); doc2["sets"]["A"]["w"] = 2
        (d / "a.json").write_text(json.dumps(doc2, ensure_ascii=False), encoding="utf-8")
        rc, out = run()
        if rc != 1 or "手で直したか" not in out:
            print(f"self-test NG: 手直しを見逃した（{rc}）"); ok = False
        (d / "a.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        # 指紋の無い書き出しは名指しする（飾りの指紋・一覧の抜けはここに出る）
        (d / "b.json").write_text(json.dumps({"$meta": {"digest": {"value": 1}}, "frames": {}}), encoding="utf-8")
        rc, out = run()
        if rc != 0 or "b.json" not in out or "持たない書き出し 1 件" not in out:
            print(f"self-test NG: 指紋の無い書き出しを名指ししていない（{rc}）"); ok = False
        rc, out = run("--allow-missing", "b.json")
        if "持たない書き出し" in out:
            print("self-test NG: --allow-missing が効いていない"); ok = False
        # 一覧を持たない: 新しい書き出しを足せば自動で照合に入る
        doc3 = {"$meta": {}, "x": [1, 2]}; doc3["$meta"]["payloadDigest"] = payload_digest(doc3)
        (d / "c.json").write_text(json.dumps(doc3), encoding="utf-8")
        rc, out = run("--allow-missing", "b.json")
        if "2/3 件を照合" not in out:
            print(f"self-test NG: 足した書き出しが照合に入らない\n   {out[:200]}"); ok = False
        # JS と同じ値になること（既知の値: aub の variants.json と同じ式）
        if fnv1a("") != 0x811C9DC5 or fnv1a("a") != 0xE40C292C:
            print("self-test NG: FNV-1a の値が既知の値と合わない"); ok = False
        # 空の置き場は 2
        for f in d.glob("*.json"): f.unlink()
        rc, _ = run()
        if rc != 2:
            print(f"self-test NG: 書き出し0件なのに通した（{rc}）"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
