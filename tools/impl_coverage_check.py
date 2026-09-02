#!/usr/bin/env python3
"""実装網羅の検査 — **Figma にあるものが、すべて実装されているか。**

2026-08-29 ユーザー確定のハーネス規則:

> Figma にあるコンポーネントは文字どおり全部実装する。Variables に登録されている
> トークン、スタイルもすべて実装する。**機械的に行い、AI がどれを作る・作らないを
> 判断しない。**

これは既存の規則「Figma に無い値は生成しない」「勝手な視覚的発明をしない」の
裏返しで、対になる。片方（無いものを作らない）だけがあり、もう片方
（あるものは全部作る）が無かったため、**AI が「使わないから作らない」を
独断で決められる状態**が残っていた。

## この検査が捕まえるもの

- 書き出し（figma/components.json ＋ frames.json の枠）にあるのに、対応表
  （component-map.json）の `impl` が空、または対応表に行そのものが無いもの
- 対応表にあるのに書き出しに無い名前（幽霊。名前の取り違え・Figma 側の削除）

## この検査が捕まえないもの

- **実装の中身が正しいか。**`impl` にクラス名が書いてあれば実装ありと数える。
  値が Figma と一致しているかは条件2（照合率）と値照合テストの領域
- **トークンとスタイルの網羅。**生成器（design/gen/）を持つ案件は、
  書き出しから機械生成しているので構造的に100%になる。生成器を持たない案件は
  `--tokens` を渡すとテーマコードの識別子で見る（弱い判定。名前が出るかしか見ない）
- 確かめた方法: 対応表から1行消して落ちること、`impl` を空にして落ちることを
  self-test で確認（--self-test）

## 使い方

    python3 <harness>/tools/impl_coverage_check.py --config impl-coverage.json

config（パスはすべて config からの相対）:

    {
      "export": "../aub-design-system/figma/components.json",
      "frames_export": "../aub-design-system/figma/frames.json",
      "component_map": "design/component-map.json",
      "tokens_export": "../aub-design-system/figma/variables.json",
      "styles_export": "../aub-design-system/figma/styles.json",
      "generated_by": "design/gen/",
      "theme_globs": ["lib/theme/*.dart"]
    }

- `generated_by` があれば、トークンとスタイルは生成器が保証しているものとして
  数え、名前の存在では見ない（生成器がある＝書き出しから作っているため）
- `theme_globs` は生成器が無い案件向けの弱い判定
"""

import argparse
import json
from datetime import datetime, timezone
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figma_names import to_identifier   # noqa: E402  規則の唯一の正


def figma_names(export_paths):
    """書き出し（複数ファイル）から、実装すべき名前の集合を返す。

    component set と単体 component だけでなく、**枠（frames.json の surfaces）も
    数える**。Header / Footer / ナビの枠は component set を持たないが実装は要る。
    片方の書き出ししか見ないと、実装済みのものを「幽霊」と誤検出する
    （2026-08-29 実測: flash-compose で Header / Footer / BottomNavigation の3件）。
    """
    names, excluded = set(), set()
    for export_path in export_paths:
        if not export_path or not export_path.exists():
            continue
        doc = json.loads(export_path.read_text(encoding="utf-8"))
        for key in ("componentSets", "singleComponents", "surfaces", "frames"):
            v = doc.get(key)
            if isinstance(v, dict):
                names |= set(v.keys())
            elif isinstance(v, list):
                names |= {e.get("name") for e in v
                          if isinstance(e, dict) and e.get("name")}
        excluded |= set((doc.get("$meta", {}).get("excluded") or {}).keys())
    return names - excluded, excluded


def mapped_impl(map_path):
    """対応表から name → 実装があるか の対応を返す。"""
    doc = json.loads(map_path.read_text(encoding="utf-8"))
    out = {}
    for c in doc.get("components", []):
        name = c.get("figma")
        if not name:
            continue
        out[name] = bool(c.get("impl"))
    return out


#: **識別子の規則は tools/figma_names.py が唯一の正**（2026-09-02 に統合）。
#: それまでここに別実装があり、文書の「唯一の正」と食い違っていた
#: （`Icon/XXL` → ここ `iconXXL` / 文書 `iconXxl`）。planttalk の実測では、
#: この差が誤検出164件のうち21件の原因だった。
identifier_of = to_identifier

#: テーマコードから識別子を拾う。**部分文字列で判定しない**（2026-09-02）。
#: それまで `identifier_of(n) not in source` で見ていたため、短い識別子が
#: 長い識別子に飲まれていた（planttalk 実測: `solidNeutral5` ⊂ `solidNeutral50`
#: など19対。**長い方だけ実装すると短い方が「実装済み」と誤判定される**）。
IDENT_RX = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

#: 例外の期限。exporter_check / expectation_source_check と同じ書式にそろえる。
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def token_names(doc):
    """書き出しから、トークン・スタイルの Figma 名を集める。"""
    names = []
    for coll in doc.values():
        if not isinstance(coll, dict):
            continue
        for k, v in coll.items():
            if isinstance(v, dict) and "name" in v:
                names.append(v["name"])
            elif isinstance(k, str) and "/" in k:
                names.append(k)
    # collections 形式（aub / 414 の variables.json）
    for c in doc.get("collections", []) if isinstance(doc.get("collections"), list) else []:
        for v in c.get("variables", []):
            if isinstance(v, dict) and v.get("name"):
                names.append(v["name"])
    for kind in ("text", "paint", "effect"):
        for s in doc.get(kind, []) if isinstance(doc.get(kind), list) else []:
            if isinstance(s, dict) and s.get("name"):
                names.append(s["name"])
    return names


def allowed_tokens(conf, today):
    """例外の宣言。**why と reviewBy が無ければ落とす**（宣言できない検査は無視される）。

    書式は exporter_check.py / expectation_source_check.py と同じ。

        "allow_tokens": [
          {"prefix": "Solid/", "why": "Primitive は公開しない方針", "reviewBy": "2026-11-30"},
          {"name": "Family/EN", "why": "...", "reviewBy": "..."}
        ]
    """
    exact, prefixes, problems = set(), [], []
    for i, e in enumerate(conf.get("allow_tokens", [])):
        where = f"allow_tokens[{i}]"
        if not isinstance(e, dict):
            problems.append(f"{where}: 形が違います（辞書が要ります）")
            continue
        why, review = e.get("why"), e.get("reviewBy")
        if not why or len(str(why)) < 8:
            problems.append(f"{where}: why が要ります（なぜ実装しないのか。8文字以上）")
        if not review or not DATE_RX.match(str(review)):
            problems.append(f"{where}: reviewBy が要ります（YYYY-MM-DD）")
        elif str(review) < today:
            problems.append(f"{where}: reviewBy {review} を過ぎています"
                            f"（{e.get('name') or e.get('prefix')}）。"
                            f"実装するか、期限を引き直して理由を書き直してください")
        if e.get("name"):
            exact.add(e["name"])
        elif e.get("prefix"):
            prefixes.append(e["prefix"])
        else:
            problems.append(f"{where}: name か prefix が要ります")
    return exact, prefixes, problems


def check_tokens(conf, base, today):
    """トークン・スタイルの網羅。

    **完全一致で判定する。** テーマコードから識別子を集めて集合にし、所属を見る。
    """
    notes, problems = [], []
    gen = conf.get("generated_by")
    if gen and (base / gen).exists():
        notes.append(f"トークン・スタイル: 生成器（{gen}）が書き出しから生成しているため"
                     f"構造的に網羅。名前の存在では見ない")
        return [], notes, []

    globs = conf.get("theme_globs")
    if not globs:
        notes.append("トークン・スタイル: 生成器も theme_globs も無いため未検査。"
                     "**網羅の保証がありません**")
        return [], notes, []

    idents, files = set(), 0
    for g in globs:
        for f in sorted(base.glob(g)):
            if f.is_file():
                files += 1
                idents |= set(IDENT_RX.findall(
                    f.read_text(encoding="utf-8", errors="ignore")))
    if files == 0:
        problems.append(f"theme_globs がどのファイルにも当たりません: {globs}\n"
                        f"    **『未実装0件』は『見ていない』という意味になります**")

    style = conf.get("identifier_style") or {}
    drop_first = set(style.get("dropFirstSegment") or [])
    exact_ok, prefix_ok, problems2 = allowed_tokens(conf, today)
    problems += problems2

    missing, checked = [], 0
    for path_key in ("tokens_export", "styles_export"):
        rel = conf.get(path_key)
        if not rel:
            continue
        doc = json.loads((base / rel).read_text(encoding="utf-8"))
        for n in token_names(doc):
            if n in exact_ok or any(n.startswith(pr) for pr in prefix_ok):
                continue
            checked += 1
            cands = {identifier_of(n)}
            # クラス名に階層を持つ流儀（`Motion.extraLong` と書く案件）。
            # 宣言したコレクションだけ、先頭の区切りを落とした形も認める
            head = re.split(r"[/&]", n)[0]
            if head in drop_first:
                tail = "/".join(re.split(r"[/&]", n)[1:])
                if tail:
                    cands.add(identifier_of(tail))
            if not (cands & idents):
                missing.append(f"{path_key}: {n}")

    # 分母のラチェット。書き出しが壊れて 223→0 になっても
    # 「0件が未実装」で緑になるのを止める（rules.json の expected_targets と同じ考え方）
    expected = conf.get("expected_tokens")
    if isinstance(expected, int) and checked < expected:
        problems.append(f"照合したトークン・スタイルが {checked} 件で、宣言"
                        f"（expected_tokens: {expected}）を下回りました。\n"
                        f"    書き出しか例外の宣言で分母が黙って減っています。\n"
                        f"    意図した減少なら expected_tokens を下げてください（差分が git に残ります）")
    elif isinstance(expected, int) and checked > expected:
        notes.append(f"トークンが {checked} 件に増えています。expected_tokens"
                     f"（{expected}）を上げてください")

    notes.append(f"トークン・スタイル: {checked} 件を完全一致で照合"
                 f"（テーマコード {files} ファイル・識別子 {len(idents)} 個）"
                 + (f"・例外 {len(exact_ok) + len(prefix_ok)} 宣言" if (exact_ok or prefix_ok) else ""))
    return missing, notes, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="Figma にあるものが全部実装されているか")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.config:
        ap.error("--config が要ります（--self-test を除く）")

    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.config.resolve().parent

    exports = [base / conf["export"]]
    for extra in ("frames_export", "styles_export_components"):
        if conf.get(extra):
            exports.append(base / conf[extra])
    cmap = base / conf["component_map"]
    for p in (exports[0], cmap):
        if not p.exists():
            print(f"ありません: {p}", file=sys.stderr)
            return 2

    targets, excluded = figma_names(exports)
    impl = mapped_impl(cmap)

    if not targets:
        print("NG: 書き出しに component set が0件です（書き出しが空の可能性）",
              file=sys.stderr)
        return 2

    # 突き合わせは**識別子に正規化して**行う。書き出しのファイルによって
    # 名前の書き方が違うため（2026-08-29 実測: 414 の frames.json は
    # surfaces を識別子（header / footer）で持つが、components.json と
    # 対応表は Figma 名（Header / Footer）で持つ。素で比べると実装済みの
    # 3件が「未実装」と「幽霊」の両方に出た）。
    impl_by_id = {}
    for name, has in impl.items():
        impl_by_id.setdefault(identifier_of(name), False)
        impl_by_id[identifier_of(name)] |= has
    target_ids = {identifier_of(n): n for n in targets}
    excluded_ids = {identifier_of(n) for n in excluded}

    unimplemented = sorted(orig for i, orig in target_ids.items()
                           if not impl_by_id.get(i))
    ghosts = sorted(n for n in impl
                    if identifier_of(n) not in target_ids
                    and identifier_of(n) not in excluded_ids)
    done = len(targets) - len(unimplemented)

    print(f"実装網羅: {done} / {len(targets)} 件")
    if excluded:
        print(f"  書き出しが除外している: {len(excluded)} 件"
              f"（{', '.join(sorted(excluded))}）")

    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    tok_missing, notes, tok_problems = check_tokens(conf, base, today)
    for n in notes:
        print(f"  {n}")

    rc = 0
    if unimplemented:
        print(f"\n未実装が {len(unimplemented)} 件あります"
              f"（Figma にあるものは全部実装する規則）:")
        for n in unimplemented:
            print(f"  - {n}")
        rc = 1
    if ghosts:
        print(f"\n対応表にあるのに書き出しに無い名前が {len(ghosts)} 件あります。"
              f"**まず書き出し器の取りこぼしを疑ってください**"
              f"（2026-09-02: 器が COMPONENT_SET しか集めず、単体の COMPONENT 4件が"
              f"書き出しに入らない案件があった。素直に読むと対応表を疑い、"
              f"**実装を削る方向へ誘導される**）。"
              f"次に名前の取り違え、最後に Figma 側の削除を疑います:")
        for n in ghosts:
            print(f"  - {n}")
        rc = 1
    if tok_problems:
        print(f"\nトークンの検査そのものが成り立っていません:", file=sys.stderr)
        for m in tok_problems:
            print(f"  - {m}", file=sys.stderr)
        rc = 1
    if tok_missing:
        print(f"\nテーマコードに見当たらないトークン・スタイルが"
              f" {len(tok_missing)} 件あります:")
        # **打ち切らない**（2026-09-02）。それまで20件で切り、切ったことも
        # 表示しなかったため、164件と言って20件しか出なかった。
        # 直すべきものを見るには道具を手で叩き直すしかなかった
        for n in tok_missing:
            print(f"  - {n}")
        print("  実装しないと決めたものは allow_tokens に why と reviewBy を"
              "書いて宣言してください（宣言できない検査は無視されるようになります）")
        rc = 1
    if rc == 0:
        print("OK: Figma にあるものはすべて実装されています。")
    return rc


def self_test():
    """落ちるケースを持つ（規律: 検査を足したら落ちるケースを1つ書く）。"""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "export.json").write_text(json.dumps({
            "componentSets": {"Buttons/M": 1, "Chips": 1},
            "singleComponents": {"Header": 1},
        }), encoding="utf-8")

        def write_map(entries):
            (base / "map.json").write_text(json.dumps({"components": entries},
                                                      ensure_ascii=False),
                                           encoding="utf-8")

        (base / "cfg.json").write_text(json.dumps({
            "export": "export.json", "component_map": "map.json"}), encoding="utf-8")
        cfg = ["--config", str(base / "cfg.json")]

        write_map([{"figma": "Buttons/M", "impl": [{"class": "A"}]},
                   {"figma": "Chips", "impl": [{"class": "B"}]},
                   {"figma": "Header", "impl": [{"class": "C"}]}])
        if main(cfg) != 0:
            print("self-test NG: 全実装なのに落ちた"); ok = False

        write_map([{"figma": "Buttons/M", "impl": [{"class": "A"}]},
                   {"figma": "Chips", "impl": []},
                   {"figma": "Header", "impl": [{"class": "C"}]}])
        if main(cfg) != 1:
            print("self-test NG: impl が空でも落ちなかった"); ok = False

        write_map([{"figma": "Buttons/M", "impl": [{"class": "A"}]},
                   {"figma": "Header", "impl": [{"class": "C"}]}])
        if main(cfg) != 1:
            print("self-test NG: 対応表に行が無くても落ちなかった"); ok = False

        write_map([{"figma": "Buttons/M", "impl": [{"class": "A"}]},
                   {"figma": "Chips", "impl": [{"class": "B"}]},
                   {"figma": "Header", "impl": [{"class": "C"}]},
                   {"figma": "Ghost/Set", "impl": [{"class": "D"}]}])
        if main(cfg) != 1:
            print("self-test NG: 幽霊の名前で落ちなかった"); ok = False

    # --- トークン照合の本体（2026-09-02 新設）--------------------------------
    # planttalk の実測: この分岐は 36 行のうち 7 行（2つの早期リターン）しか
    # self-test を通っておらず、**トークン照合の本体は1行も通っていなかった**。
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "export.json").write_text(json.dumps(
            {"componentSets": {"Buttons/M": 1}}), encoding="utf-8")
        (base / "map.json").write_text(json.dumps(
            {"components": [{"figma": "Buttons/M", "impl": [{"class": "A"}]}]}),
            encoding="utf-8")
        (base / "vars.json").write_text(json.dumps({"collections": [
            {"name": "ColorPrimitive", "variables": [
                {"name": "Solid/Neutral/5"}, {"name": "Solid/Neutral/50"},
                {"name": "Icon/XXL"}]}]}), encoding="utf-8")

        def theme(body):
            (base / "theme.dart").write_text(body, encoding="utf-8")

        def cfg(**extra):
            d = {"export": "export.json", "component_map": "map.json",
                 "tokens_export": "vars.json", "theme_globs": ["theme.dart"]}
            d.update(extra)
            (base / "c2.json").write_text(json.dumps(d, ensure_ascii=False),
                                          encoding="utf-8")
            return ["--config", str(base / "c2.json")]

        def expect(rc, argv, msg):
            nonlocal ok
            got = main(argv)
            if got != rc:
                print(f"self-test NG: {msg}（戻り値 {got}・期待 {rc}）"); ok = False

        theme("const solidNeutral5 = 1; const solidNeutral50 = 2; const iconXxl = 3;")
        expect(0, cfg(), "全部あるのに落ちた")

        # **部分文字列で飲まれないこと**（この回の本体）。
        # 長い方だけ実装したとき、短い方が「実装済み」と誤判定されてはいけない
        theme("const solidNeutral50 = 2; const iconXxl = 3;")
        expect(1, cfg(), "solidNeutral5 が solidNeutral50 に飲まれた")

        # 識別子の規則（Icon/XXL → iconXxl。iconXXL では当たらない）
        theme("const solidNeutral5 = 1; const solidNeutral50 = 2; const iconXXL = 3;")
        expect(1, cfg(), "iconXXL を iconXxl として通した")

        theme("const solidNeutral5 = 1; const solidNeutral50 = 2; const iconXxl = 3;")

        # theme_globs が当たらない＝「未実装0件」は「見ていない」の意味
        expect(1, cfg(theme_globs=["no_such_*.dart"]), "空振りなのに通した")

        # allow の宣言に why / reviewBy が無ければ落ちる
        expect(1, cfg(allow_tokens=[{"name": "Icon/XXL"}]),
               "why と reviewBy が無い allow を通した")
        expect(1, cfg(allow_tokens=[{"name": "Icon/XXL", "why": "使わない方針です",
                                     "reviewBy": "2020-01-01"}]),
               "reviewBy を過ぎた allow を通した")
        theme("const solidNeutral5 = 1; const solidNeutral50 = 2;")
        expect(0, cfg(allow_tokens=[{"name": "Icon/XXL", "why": "使わない方針です",
                                     "reviewBy": "2099-12-31"}]),
               "正しい allow で落ちた")

        # 分母のラチェット
        theme("const solidNeutral5 = 1; const solidNeutral50 = 2; const iconXxl = 3;")
        expect(1, cfg(expected_tokens=99), "分母が宣言を下回ったのに通した")
        expect(0, cfg(expected_tokens=3), "分母が宣言どおりなのに落ちた")

        # クラス名に階層を持つ流儀（Motion.extraLong）
        (base / "vars2.json").write_text(json.dumps({"collections": [
            {"name": "Duration", "variables": [{"name": "Duration/ExtraLong"}]}]}),
            encoding="utf-8")
        theme("class Motion { static const extraLong = 1; }")
        expect(1, cfg(tokens_export="vars2.json"),
               "宣言なしで先頭の区切りを落として通した")
        expect(0, cfg(tokens_export="vars2.json",
                      identifier_style={"dropFirstSegment": ["Duration"]}),
               "dropFirstSegment を宣言したのに落ちた")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
