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
import re
import sys
from pathlib import Path


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


def identifier_of(figma_name):
    """Figma 名 → 識別子（generation-rules の唯一の規則）。

    `/` と `&` で区切り、記号を落として lowerCamelCase で連結。
    """
    parts = [p for p in re.split(r"[/&]", figma_name) if p]
    words = []
    for i, p in enumerate(parts):
        p = re.sub(r"[^0-9A-Za-z]", "", p)
        if not p:
            continue
        words.append(p[0].lower() + p[1:] if i == 0 else p[0].upper() + p[1:])
    return "".join(words)


def check_tokens(conf, base):
    """トークン・スタイルの網羅。生成器があれば構造的に保証されるものとして扱う。"""
    notes = []
    gen = conf.get("generated_by")
    if gen and (base / gen).exists():
        notes.append(f"トークン・スタイル: 生成器（{gen}）が書き出しから生成しているため"
                     f"構造的に網羅。名前の存在では見ない")
        return [], notes

    globs = conf.get("theme_globs")
    if not globs:
        notes.append("トークン・スタイル: 生成器も theme_globs も無いため未検査。"
                     "**網羅の保証がありません**")
        return [], notes

    source = ""
    for g in globs:
        for f in sorted(base.glob(g)):
            if f.is_file():
                source += f.read_text(encoding="utf-8", errors="ignore")

    missing = []
    for key, path_key in (("variables", "tokens_export"), ("styles", "styles_export")):
        p = conf.get(path_key)
        if not p:
            continue
        doc = json.loads((base / p).read_text(encoding="utf-8"))
        names = []
        for coll in doc.values():
            if isinstance(coll, dict):
                for k, v in coll.items():
                    if isinstance(v, dict) and "name" in v:
                        names.append(v["name"])
                    elif isinstance(k, str) and "/" in k:
                        names.append(k)
        for n in names:
            if identifier_of(n) not in source:
                missing.append(f"{path_key}: {n}")
    notes.append(f"トークン・スタイル: テーマコードの識別子で判定（弱い判定。"
                 f"名前が出るかしか見ていない）")
    return missing, notes


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

    tok_missing, notes = check_tokens(conf, base)
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
        print(f"\n対応表にあるのに書き出しに無い名前が {len(ghosts)} 件あります"
              f"（名前の取り違えか、Figma 側の削除）:")
        for n in ghosts:
            print(f"  - {n}")
        rc = 1
    if tok_missing:
        print(f"\nテーマコードに見当たらないトークン・スタイルが"
              f" {len(tok_missing)} 件あります:")
        for n in tok_missing[:20]:
            print(f"  - {n}")
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

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
