#!/usr/bin/env python3
"""1つの値が複数ファイル・複数担当に散るのを見る（2026-09-04 新設・#45）。

## 実害（FlashEnglish）

アプリの表示名は **5ファイル6か所**に散っていて、**担当マシンが3つに分かれます。**

| 場所 | 担当 |
|---|---|
| `ios/Runner/Info.plist` の `CFBundleDisplayName` / `CFBundleName` | Mac mini |
| `android/app/src/main/AndroidManifest.xml` の `android:label` | Windows |
| `lib/main.dart` の `MaterialApp title` | Windows |
| `web/index.html` の `<title>` ほか | MacBook Air |
| `web/manifest.json` の `name` / `short_name` | MacBook Air |

**変える前は3通りが混在していました**（`Flash English` / `flash_compose` /
`FlashEnglish`）。**誰も気づいていませんでした。**

一方で**変えてはいけないもの**も近くにあります。`pubspec.yaml` の
`name: flash_compose`（変えると全 import が壊れる）と、バンドル ID
`com.rightdesign.flash_compose`（ストアの同一性が切れる）。
**「名前を変えて」と言われたときに、変えるものと変えないものの区別が
文書にしかありませんでした。**

## 宣言（`design/platform-values.json`）

    {
      "values": {
        "displayName": {
          "正": "Flash English",
          "なぜ": "2026-09-04 ユーザー確定「アプリ名は「Flash English」にします」",
          "場所": [
            {"file": "ios/Runner/Info.plist", "key": "CFBundleDisplayName",
             "owner": "Mac mini"},
            {"file": "web/manifest.json", "key": "name", "owner": "MacBook Air"}
          ],
          "未対応": [
            {"file": "android/…/AndroidManifest.xml", "owner": "Windows",
             "why": "Windows がまだビルドしていない"}
          ]
        }
      },
      "変えないもの": [
        {"file": "pubspec.yaml", "値": "flash_compose",
         "why": "Dart のパッケージ名。変えると全 import が壊れる"}
      ]
    }

## 落とすもの

| | |
|---|---|
| 宣言に載っている場所が正と違う | 「未対応」に挙がっていない限り落とす |
| **未対応の宣言が古い**（すでに直っている） | 落とす。**直したのに宣言だけ残る化石**を防ぐ |
| 宣言の担当が `machine-scope.json` と食い違う | 落とす |
| **変えてはいけない値が変わっている** | 落とす |

## 散らばりの候補を導く（2026-09-05・#73）

それまで「宣言に載っていない場所は見ない。一覧は人が作る」と自分で書いていた。
**一覧に無いものは、無いのではなく見えない**（#66 と同じ形）。そこで、正の値が
プラットフォーム側（`ios/ android/ web/ lib/ macos/ windows/ linux/` と
`pubspec.yaml`）の**どこに現れるかを全部歩いて導く。** 綴りの揺れも拾う
（`Flash English` / `FlashEnglish` / `flash_english` / `flash-english`。
FlashEnglish で3通りが混在していた形）。

- 宣言（`場所`・`未対応`・`対象外`）に無い候補は**落とす**
- 網羅率（候補のうち宣言済み）を**毎回出す**。0件・全件だけでは足りない
- 候補が 0 なら「散らばっていない」ではなく**「正の値がどこにも書かれていない」**。それも出す

    "対象外": [{"file": "lib/l10n/app_ja.arb", "why": "翻訳の本文。名前としての使用ではない"}]

## 捕まえないもの

- 正と綴りが全く違う旧名（`flash_compose` が `Flash English` の散らばりだとは
  分からない）。旧名は `変えないもの` か、値ごとの `場所` で見る
- 確かめた方法: --self-test（4つそれぞれが仕込みで落ちること・宣言に無い候補で落ちること）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


def read_value(path, key):
    """ファイルの形ごとに、そのキーの値を読む。**案件が正規表現を書き直さない。**

    戻り: (値の一覧, 読めなかった理由)
    """
    if not path.exists():
        return [], f"ファイルがありません: {path}"
    text = path.read_text(encoding="utf-8", errors="ignore")
    suf = path.suffix.lower()

    if suf == ".plist":
        # <key>CFBundleName</key><string>値</string>
        m = re.search(r"<key>\s*" + re.escape(key) + r"\s*</key>\s*"
                      r"<string>(.*?)</string>", text, re.S)
        return ([m.group(1).strip()] if m else []), None
    if suf == ".xml":
        # android:label="値"
        m = re.findall(re.escape(key) + r'\s*=\s*"([^"]*)"', text)
        return m, None
    if suf in (".json", ".arb"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as e:
            return [], f"JSON が読めません: {path}: {e}"
        cur = doc
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return [], None
        return ([cur] if isinstance(cur, str) else []), None
    if suf in (".html", ".htm"):
        if key == "title":
            m = re.search(r"<title>(.*?)</title>", text, re.S)
            return ([m.group(1).strip()] if m else []), None
        m = re.findall(r'name\s*=\s*"' + re.escape(key) + r'"\s+content\s*=\s*"([^"]*)"',
                       text)
        return m, None
    if suf in (".dart", ".yaml", ".yml", ".kt", ".swift", ".ts", ".js"):
        # `key: '値'` / `key: "値"` / `key: 値`
        m = re.findall(re.escape(key) + r"\s*:\s*['\"]([^'\"]*)['\"]", text)
        if not m:
            m = re.findall(re.escape(key) + r"\s*:\s*([^\s,#]+)", text)
        return m, None
    if suf in (".pbxproj", ".xcconfig"):
        # PRODUCT_NAME = "値";  /  PRODUCT_NAME = 値
        m = re.findall(re.escape(key) + r'\s*=\s*"?([^";\n]*?)"?\s*(?:;|\n|$)', text)
        return [x.strip() for x in m if x.strip()], None
    if suf == ".strings":
        # "key" = "値";
        m = re.findall(r'"' + re.escape(key) + r'"\s*=\s*"([^"]*)"', text)
        return m, None
    if suf == ".properties":
        m = re.findall(r"^\s*" + re.escape(key) + r"\s*[=:]\s*(.*?)\s*$", text, re.M)
        return m, None
    if suf in (".gradle", ".kts"):
        # applicationId "値"  /  applicationId = "値"
        m = re.findall(re.escape(key) + r"""\s*=?\s*['"]([^'"]*)['"]""", text)
        return m, None
    return [], f"読み方が分からない形です: {path.suffix}"


def owners_of(scope_path):
    """machine-scope.json から パス接頭辞 → 担当 を作る。"""
    if not scope_path or not scope_path.exists():
        return None
    try:
        doc = json.loads(scope_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    out = {}
    for name, body in (doc.get("machines") or {}).items():
        paths = body if isinstance(body, list) else (body or {}).get("owns") or []
        for p in paths:
            out[str(p).rstrip("/")] = name
    return out


def owner_for(rel, owners):
    best, who = -1, None
    for p, name in (owners or {}).items():
        if rel == p or rel.startswith(p + "/"):
            if len(p) > best:
                best, who = len(p), name
    return who


#: 候補を歩く場所（プラットフォーム側）。一覧はディレクトリだけで、ファイルは全部歩く
CANDIDATE_DIRS = ("ios", "android", "web", "lib", "macos", "windows", "linux")
CANDIDATE_ROOT_FILES = ("pubspec.yaml",)
SKIP_DIRS = {"build", ".dart_tool", "Pods", ".gradle", "node_modules", ".symlinks",
             ".plugin_symlinks", "ephemeral", "DerivedData"}
TEXT_SUFFIXES = {".plist", ".xml", ".json", ".arb", ".html", ".htm", ".dart", ".yaml",
                 ".yml", ".kt", ".kts", ".gradle", ".swift", ".ts", ".js", ".xcconfig",
                 ".pbxproj", ".entitlements", ".storyboard", ".strings", ".properties",
                 ".cc", ".cpp", ".h", ".rc", ".cmake", ".txt"}


def value_pattern(want):
    """正の値から、綴りの揺れも拾う正規表現を作る。

    `Flash English` → `Flash English` / `FlashEnglish` / `flash_english` / `flash-english`
    （FlashEnglish で3通りが混在していた形）。空白・`_`・`-` の有無と大小を無視する。
    """
    parts = re.findall(r"[A-Za-z0-9]+|[^\sA-Za-z0-9_\-]", want)
    if not parts:
        return None
    return re.compile(r"[\s_\-]*".join(re.escape(p) for p in parts), re.IGNORECASE)


def candidate_files(base):
    """プラットフォーム側のテキストファイルを全部歩く（一覧を持たない）。"""
    out = [base / n for n in CANDIDATE_ROOT_FILES if (base / n).is_file()]
    for d in CANDIDATE_DIRS:
        dp = base / d
        if not dp.is_dir():
            continue
        for f in sorted(dp.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if SKIP_DIRS & set(f.relative_to(base).parts[:-1]):
                continue
            try:
                if f.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue
            out.append(f)
    return out


def find_candidates(base, values):
    """値ごとに、正の値（綴りの揺れ込み）が現れるファイルを返す: {値名: {rel: [行]}}"""
    pats = {n: value_pattern(v["正"]) for n, v in values.items()
            if isinstance(v.get("正"), str)}
    pats = {n: rx for n, rx in pats.items() if rx is not None}
    found = {n: {} for n in pats}
    if not pats:
        return found
    for f in candidate_files(base):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = f.relative_to(base).as_posix()
        lines = text.splitlines()
        for n, rx in pats.items():
            hit = [i for i, line in enumerate(lines, 1) if rx.search(line)]
            if hit:
                found[n][rel] = hit
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description="複数担当にまたがる値を見る")
    ap.add_argument("--config", type=Path,
                    default=Path("design/platform-values.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--scope", type=Path, default=Path("design/machine-scope.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"宣言がありません: {args.config}\n"
              f"  **複数ファイルに散る値を、誰も見ていない状態です。**\n"
              f"  書式はこの道具の冒頭を参照してください。", file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"宣言が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.root.resolve()
    owners = owners_of(base / args.scope if not args.scope.is_absolute()
                       else args.scope)

    errs, checked = [], 0
    values = conf.get("values") or {}
    if not values and not conf.get("変えないもの"):
        print(f"宣言に値が1つもありません: {args.config}\n"
              f"  **0件は「散らばりなし」ではなく「見ていない」です。**",
              file=sys.stderr)
        return 2

    for name, v in sorted(values.items()):
        want = v.get("正")
        if not isinstance(want, str):
            errs.append(f"  {name}: `正` がありません（**唯一の正が無い宣言**です）")
            continue
        pending = {(str(p.get("file")), str(p.get("key", "")))
                   for p in (v.get("未対応") or [])}
        for p in (v.get("未対応") or []):
            if not str(p.get("why", "")).strip():
                errs.append(f"  {name}: 未対応の宣言に理由がありません: {p.get('file')}")
        for loc in (v.get("場所") or []):
            rel = str(loc.get("file", ""))
            key = str(loc.get("key", ""))
            checked += 1
            got, why = read_value(base / rel, key)
            if why:
                errs.append(f"  {name}: {why}")
                continue
            is_pending = (rel, key) in pending or (rel, "") in pending
            if not got:
                if not is_pending:
                    errs.append(f"  {name}: {rel} の `{key}` が読めません"
                                f"（キーの綴りか場所が違います）")
                continue
            bad = [g for g in got if g != want]
            if bad and not is_pending:
                errs.append(f"  {name}: {rel} の `{key}` が `{bad[0]}` です"
                            f"（正は `{want}`）\n"
                            f"    担当: {loc.get('owner') or '（宣言なし）'}")
            if not bad and is_pending:
                # **直したのに宣言だけ残る化石を防ぐ**
                errs.append(f"  {name}: {rel} の `{key}` は**すでに正しい**のに、"
                            f"未対応の宣言が残っています。\n"
                            f"    **宣言のほうが古くなっています。**消してください。")
            # 担当の食い違い
            if owners is not None and loc.get("owner"):
                real = owner_for(rel, owners)
                if real and real != loc["owner"]:
                    errs.append(f"  {name}: {rel} の担当が宣言（{loc['owner']}）と"
                                f"machine-scope.json（{real}）で食い違っています。")

    for keep in (conf.get("変えないもの") or []):
        rel, want = str(keep.get("file", "")), keep.get("値")
        checked += 1
        if not str(keep.get("why", "")).strip():
            errs.append(f"  変えないもの {rel}: 理由がありません")
        f = base / rel
        if not f.exists():
            errs.append(f"  変えないもの {rel}: ファイルがありません")
            continue
        if isinstance(want, str) and want not in f.read_text(encoding="utf-8",
                                                             errors="ignore"):
            errs.append(f"  **変えてはいけない値が変わっています**: {rel} の "
                        f"`{want}` が見つかりません\n"
                        f"    なぜ変えないか: {keep.get('why')}")

    # ─── 散らばりの候補（#73）: 宣言に載っていない場所を導いて名指しする ───
    found = find_candidates(base, values)
    cover = []
    for name, v in sorted(values.items()):
        if name not in found:
            continue
        declared = {str(p.get("file")) for p in (v.get("場所") or [])}
        declared |= {str(p.get("file")) for p in (v.get("未対応") or [])}
        excluded = set()
        for p in (v.get("対象外") or []):
            if not str(p.get("why", "")).strip():
                errs.append(f"  {name}: 対象外の宣言に理由がありません: {p.get('file')}")
            excluded.add(str(p.get("file")))
        cands = found[name]
        if not cands:
            cover.append(f"  {name}: 正 `{v['正']}` はプラットフォーム側のどこにも現れません"
                         f"（候補 0。**散らばっていないのではなく、正の値が書かれていない**）")
            continue
        in_decl = [r for r in cands if r in declared]
        in_excl = [r for r in cands if r in excluded and r not in declared]
        unknown = [r for r in cands if r not in declared and r not in excluded]
        cover.append(f"  {name}: 候補 {len(cands)} ファイルのうち宣言済み "
                     f"{len(in_decl) + len(in_excl)}（場所・未対応 {len(in_decl)} / "
                     f"対象外 {len(in_excl)} / **宣言に無い {len(unknown)}**）")
        for r in unknown:
            ln = cands[r]
            errs.append(f"  {name}: {r}:{ln[0]} に正の綴りが現れますが、宣言にありません"
                        f"（{len(ln)} 行）。\n"
                        f"    `場所` に足して照合するか、`未対応` か `対象外` に理由つきで"
                        f"入れてください。**一覧に無いものは、無いのではなく見えていません。**")
    print("散らばりの網羅（プラットフォーム側を全部歩いた）:")
    for line in cover:
        print(line)

    if errs:
        print(f"散らばった値が食い違っています（{checked} 箇所を見ました）:",
              file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    print(f"散らばった値: {len(values)} 件 / {checked} 箇所、すべて一致します。")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ios" / "Runner").mkdir(parents=True)
        (root / "android").mkdir()
        (root / "web").mkdir()
        (root / "design").mkdir()
        plist = root / "ios" / "Runner" / "Info.plist"
        xml = root / "android" / "AndroidManifest.xml"
        js = root / "web" / "manifest.json"
        html = root / "web" / "index.html"
        pub = root / "pubspec.yaml"
        cp = root / "design" / "platform-values.json"
        scope = root / "design" / "machine-scope.json"

        def write(name="Flash English", label="Flash English"):
            plist.write_text("<plist><dict>\n<key>CFBundleDisplayName</key>\n"
                             f"<string>{name}</string>\n</dict></plist>\n",
                             encoding="utf-8")
            xml.write_text(f'<manifest><application android:label="{label}"/>'
                           f'</manifest>\n', encoding="utf-8")
            js.write_text(json.dumps({"name": name, "short_name": name},
                                     ensure_ascii=False), encoding="utf-8")
            html.write_text(f"<html><head><title>{name}</title>\n"
                            f'<meta name="apple-mobile-web-app-title" '
                            f'content="{name}">\n</head></html>\n',
                            encoding="utf-8")
        write()
        pub.write_text("name: flash_compose\nversion: 1.0.0\n", encoding="utf-8")
        scope.write_text(json.dumps({"machines": {
            "Mac mini": ["ios/"], "Windows": ["android/"],
            "MacBook Air": ["web/"]}}), encoding="utf-8")

        BASE = {"values": {"displayName": {
            "正": "Flash English",
            "場所": [
                {"file": "ios/Runner/Info.plist", "key": "CFBundleDisplayName",
                 "owner": "Mac mini"},
                {"file": "android/AndroidManifest.xml", "key": "android:label",
                 "owner": "Windows"},
                {"file": "web/manifest.json", "key": "name", "owner": "MacBook Air"},
                {"file": "web/index.html", "key": "title", "owner": "MacBook Air"},
            ]}},
            "変えないもの": [{"file": "pubspec.yaml", "値": "flash_compose",
                          "why": "Dart のパッケージ名。変えると全 import が壊れる"}]}

        def run(conf):
            cp.write_text(json.dumps(conf, ensure_ascii=False), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--config", str(cp), "--root", str(root),
                           "--scope", str(scope)])
            return rc, buf.getvalue()

        rc, out = run(BASE)
        if rc != 0:
            print(f"self-test NG: 全部そろっているのに落ちた（{rc}）\n   {out[:400]}")
            ok = False

        # 1つだけ古い → 落ちる
        write(label="Flash Compose")   # わざと違う値（旧名）。食い違いの例
        rc, out = run(BASE)
        if rc != 1 or "Flash Compose" not in out:
            print(f"self-test NG: 食い違いを見逃した（{rc}）\n   {out[:300]}"); ok = False
        if "Windows" not in out:
            print("self-test NG: 担当を出していない"); ok = False

        # 未対応に挙げれば通る（理由つき）
        pend = json.loads(json.dumps(BASE))
        pend["values"]["displayName"]["未対応"] = [
            {"file": "android/AndroidManifest.xml", "key": "android:label",
             "owner": "Windows", "why": "Windows がまだビルドしていない"}]
        rc, out = run(pend)
        if rc != 0:
            print(f"self-test NG: 未対応の宣言があるのに落ちた（{rc}）\n   {out[:300]}")
            ok = False
        # 理由が無ければ落ちる
        p2 = json.loads(json.dumps(pend))
        p2["values"]["displayName"]["未対応"][0]["why"] = "  "
        if run(p2)[0] != 1:
            print("self-test NG: 理由の無い未対応を通した"); ok = False

        # **直したのに宣言だけ残る化石**
        write()
        rc, out = run(pend)
        if rc != 1 or "すでに正しい" not in out:
            print(f"self-test NG: 古い未対応の宣言を通した（{rc}）"); ok = False

        # 担当の食い違い
        wrong = json.loads(json.dumps(BASE))
        wrong["values"]["displayName"]["場所"][1]["owner"] = "Mac mini"
        rc, out = run(wrong)
        if rc != 1 or "食い違っています" not in out:
            print(f"self-test NG: 担当の食い違いを見逃した（{rc}）"); ok = False

        # **変えてはいけない値が変わっている**
        pub.write_text("name: flash_english\n", encoding="utf-8")
        rc, out = run(BASE)
        if rc != 1 or "変えてはいけない値が変わっています" not in out:
            print(f"self-test NG: 変えないものの変化を見逃した（{rc}）"); ok = False
        pub.write_text("name: flash_compose\n", encoding="utf-8")

        # ─── 宣言に無い候補（#73）────────────────────────────────
        rc, out = run(BASE)
        if "候補 4 ファイルのうち宣言済み 4" not in out:
            print(f"self-test NG: 網羅率を出していない\n   {out[:300]}"); ok = False
        (root / "lib").mkdir(exist_ok=True)
        (root / "lib" / "main.dart").write_text(
            "runApp(MaterialApp(title: 'Flash English'));\n", encoding="utf-8")
        rc, out = run(BASE)
        if rc != 1 or "lib/main.dart:1" not in out or "宣言に無い 1" not in out:
            print(f"self-test NG: 宣言に無い候補を見逃した（{rc}）\n   {out[:400]}"); ok = False
        # 綴りの揺れ（FlashEnglish / flash_english）も候補
        (root / "lib" / "main.dart").write_text(
            "const app = 'FlashEnglish'; const id = 'flash_english';\n", encoding="utf-8")
        rc, out = run(BASE)
        if rc != 1 or "lib/main.dart" not in out:
            print(f"self-test NG: 綴りの揺れを候補にしていない（{rc}）"); ok = False
        # `場所` に足せば照合される（読めるキーで）
        (root / "lib" / "main.dart").write_text(
            "runApp(MaterialApp(title: 'Flash English'));\n", encoding="utf-8")
        loc = json.loads(json.dumps(BASE))
        loc["values"]["displayName"]["場所"].append(
            {"file": "lib/main.dart", "key": "title", "owner": "Windows"})
        rc, out = run(loc)
        if rc != 0:
            print(f"self-test NG: 場所に足したのに落ちた（{rc}）\n   {out[:300]}"); ok = False
        # `対象外` は理由つきなら通り、理由が無ければ落ちる
        ex = json.loads(json.dumps(BASE))
        ex["values"]["displayName"]["対象外"] = [
            {"file": "lib/main.dart", "why": "起動時の題。表示名とは別に管理"}]
        if run(ex)[0] != 0:
            print("self-test NG: 理由つきの対象外を通さない"); ok = False
        ex["values"]["displayName"]["対象外"][0]["why"] = ""
        if run(ex)[0] != 1:
            print("self-test NG: 理由の無い対象外を通した"); ok = False
        (root / "lib" / "main.dart").unlink()
        # 候補 0 は「書かれていない」と出す
        zero = json.loads(json.dumps(BASE))
        zero["values"]["ghost"] = {"正": "Nowhere Name", "場所": []}
        rc, out = run(zero)
        if "書かれていない" not in out:
            print("self-test NG: 候補 0 を「書かれていない」と出していない"); ok = False

        # 正が無い宣言
        nov = {"values": {"x": {"場所": []}}}
        rc, out = run(nov)
        if rc != 1 or "唯一の正が無い" not in out:
            print(f"self-test NG: 正の無い宣言を通した（{rc}）"); ok = False

        # 宣言が空／無い
        if run({"values": {}})[0] != 2:
            print("self-test NG: 空の宣言を通した"); ok = False
        cp.unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--config", str(cp), "--root", str(root)])
        if rc != 2:
            print(f"self-test NG: 宣言が無いのに通した（{rc}）"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
