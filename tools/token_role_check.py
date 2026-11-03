#!/usr/bin/env python3
"""**色のトークンを、Figma が決めた用途と組み合わせで使っているか**（候補3・2026-11-03）。

外部の実践例（Serendie の Figma プラグイン `Rules.ts` の文字色 × 背景色の表、`serendie-overview` の
「見た目が似ているかではなく用途で選ぶ」）から取り入れた。

## 見るもの

1. **用途違い（CSS）**: Figma の変数の scopes（TEXT_FILL・FRAME_FILL・SHAPE_FILL・STROKE_COLOR・EFFECT_COLOR）
   から、トークンの役割（名前の先頭: Frame・Text・Shape・Stroke・Effects）ごとに使ってよい用途を導き、
   CSS のプロパティと合わない使い方を落とす（文字用の色を `background` に使う、など）。
   書き出しに scopes が無いときは、役割の名前から導く（**そう導いたと出す**）。
2. **組み合わせ（CSS）**: Figma の書き出し（画面・部品）の中で、**実際に「この文字色がこの面の上にある」**と
   出てくる組み合わせを集め、CSS の**同じ規則の中で** `color` と `background` に表に無い組み合わせを書いたら落とす。
3. **Flutter 向けの規則を生成する**（`--emit-flutter`）: aub に手書きで入っていた scope-* の規則を、
   Figma から作る。`--check-flutter` で、生成物が古くなっていないかを見る。

## 見ないもの（限界）

- 組み合わせは**同じ規則の中**だけ。文字色を子に、面を親に書いた場合は、描画の点検（web_render_check）の領分
- Flutter の組み合わせは見ない（規則の生成は用途だけ）

## 終了コード

    0  用途も組み合わせも Figma どおり（宣言つきは除く）
    1  用途違い・表に無い組み合わせがある／宣言に理由が無い／生成物が古い
    2  **確かめられなかった**（設定・変数・CSS が無い、色の役割が1つも分からない、組み合わせの表が空）
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401

#: Figma の scopes → 用途
SCOPE_USAGE = {"TEXT_FILL": "text", "FRAME_FILL": "surface", "SHAPE_FILL": "shape",
               "STROKE_COLOR": "stroke", "EFFECT_COLOR": "effect"}
#: scopes が書き出しに無いときに、役割の名前から導く用途
ROLE_USAGE = {"frame": {"surface"}, "text": {"text"}, "shape": {"shape"},
              "stroke": {"stroke"}, "effects": {"effect"}, "action": {"surface"}}
#: CSS のプロパティ → 用途
#: CSS では Figma の「図形」を background で描き（丸・四角）、SVG のアイコンの色を color で渡すので、
#: color と background は図形の色も受ける（2026-11-03 portfolio に当てて分かった）
PROP_USAGE = {"color": {"text", "shape"}, "background": {"surface", "shape"},
              "background-color": {"surface", "shape"},
              "border": "stroke", "border-color": "stroke", "border-top": "stroke",
              "border-right": "stroke", "border-bottom": "stroke", "border-left": "stroke",
              "border-top-color": "stroke", "border-right-color": "stroke",
              "border-bottom-color": "stroke", "border-left-color": "stroke",
              "outline": "stroke", "outline-color": "stroke",
              "box-shadow": "effect", "text-shadow": "effect",
              "fill": "shape", "stroke": {"shape", "stroke"}}
#: ぼかしの無い縁取りだけの影（`inset 0 0 0 1px …`）は**線**。Figma の内側の線を描く定番の書き方
#: （2026-11-03 portfolio に当てて、影と読んで 30 件以上の偽の指摘を出した）
RING_RX = re.compile(r"^(?:inset\s+)?0(?:px)?\s+0(?:px)?\s+0(?:px)?\s+(?:[\d.]+(?:px|rem|em)?|var\([^()]*\)|calc\((?:[^()]|\([^()]*\))*\))\s+var\(")
USAGE_JA = {"text": "文字", "surface": "面", "shape": "図形・アイコン", "stroke": "線", "effect": "影"}
#: Flutter の書き方 → 用途（aub の手書きの scope-* と同じ形）
FLUTTER_SHAPES = {
    "text": r"(?:TextStyle\(|\.copyWith\()(?:[^()]|\([^()]*\)){0,300}?color:\s*",
    "surface": r"BoxDecoration\((?:[^()]|\([^()]*\)){0,400}?color:\s*",
    "stroke": r"Border(?:Side)?(?:\.all)?\((?:[^()]|\([^()]*\)){0,300}?color:\s*",
    "effect": r"BoxShadow\((?:[^()]|\([^()]*\)){0,300}?color:\s*",
}
#: 生成した規則の仕込み（_selftest）の型。{c} に `AppColor.xxx` が入る（#180）。
#: 生成物に仕込みが無いと、段「ルールの仕込み」が「確かめられない」で止まり、
#: 案件で手で足すと --check-flutter（作り直して一致するか）が崩れる
FLUTTER_EXAMPLES = {
    "text": "Text('a', style: TextStyle(fontSize: 14, color: {c}))",
    "surface": "Container(decoration: BoxDecoration(borderRadius: BorderRadius.circular(8), color: {c}))",
    "stroke": "BoxDecoration(border: Border.all(width: 1, color: {c}))",
    "effect": "BoxDecoration(boxShadow: [BoxShadow(blurRadius: 4, color: {c})])",
}
RULE_RX = re.compile(r"([^{}]+)\{([^{}]*)\}")
COMMENT_RX = re.compile(r"/\*.*?\*/", re.S)
VAR_RX = re.compile(r"var\(\s*(--[\w-]+)")


def css_name(figma_name):
    """`Frame/Neutral/Default` → `--frame-neutral-default`"""
    return "--" + re.sub(r"[\s/]+", "-", figma_name.strip()).lower()


def camel(figma_name):
    """`Frame/Neutral/Default` → `frameNeutralDefault`"""
    parts = [p for p in re.split(r"[\s/_-]+", figma_name.strip()) if p]
    return parts[0].lower() + "".join(p[:1].upper() + p[1:] for p in parts[1:]) if parts else ""


def load_variables(path):
    """書き出しの形を問わず、色の変数を `{名前: scopes か None}` で返す。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}

    def walk(o, coll=""):
        if isinstance(o, dict):
            name = o.get("name") if isinstance(o.get("name"), str) else None
            typ = o.get("type") or o.get("resolvedType")
            if name and typ:
                if typ == "COLOR":
                    out.setdefault(name, o.get("scopes") if isinstance(o.get("scopes"), list) else None)
                return
            if "n" in o and isinstance(o.get("n"), str) and ("v" in o or "m" in o):
                if coll.lower().startswith("color"):     # 414 の rows 形式
                    out.setdefault(o["n"], None)
                return
            for k, v in o.items():
                walk(v, k if isinstance(v, dict) and coll == "" and k not in ("$meta",) else coll)
        elif isinstance(o, list):
            for v in o:
                walk(v, coll)
    walk(d.get("variables", d) if isinstance(d, dict) else d)
    return out


def role_usage(variables):
    """役割（名前の先頭）→ 使ってよい用途の集合。`(表, 名前から導いた役割の一覧)`"""
    table, from_names = {}, set()
    for name, scopes in variables.items():
        role = name.split("/")[0].strip().lower()
        if scopes is None:
            if role in ROLE_USAGE:
                table.setdefault(role, set()).update(ROLE_USAGE[role])
                from_names.add(role)
            continue
        uses = {SCOPE_USAGE[s] for s in scopes if s in SCOPE_USAGE}
        if "ALL_SCOPES" in scopes or "ALL_FILLS" in scopes:
            uses = set(USAGE_JA)
        if uses:
            table.setdefault(role, set()).update(uses)
    return table, sorted(from_names)


def _rows_pairs(rows, pairs, comp_open):
    """1つの行の束から組を集める。部品を置いた行では、部品の中の「上に面の無い文字」を、
    置いた場所の面と組にする。返り値は、この束の中で上に面の無かった文字。"""
    stack, open_texts = [], set()   # (深さ, 面の色)
    for row in rows:
        cols = row.split("|")
        if len(cols) < 3 or not cols[0].isdigit():
            continue
        depth = int(cols[0])
        fill = next((c[5:] for c in cols if c.startswith("fill=")), None)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        surf = next((s for _, s in reversed(stack) if s), None)
        if cols[2] == "TEXT":
            if fill:
                if surf:
                    pairs.add((css_name(fill), css_name(surf)))
                else:
                    open_texts.add(css_name(fill))
            continue
        if cols[2] == "INSTANCE":
            of = next((c[3:] for c in cols if c.startswith("of=")), "")
            for t in comp_open.get(of.split("/")[0], ()):
                if surf or fill:
                    pairs.add((t, css_name(fill or surf)))
        stack.append((depth, fill if fill and not fill.lower().startswith(("text/", "shape/", "stroke/", "effects/")) else None))
    return open_texts


def figma_pairs(paths):
    """書き出しの行から、(文字色, その上の面の色) の組を集める。"""
    pairs, comp_open, docs = set(), {}, []
    for path in paths:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        docs.append(d)
        for name, s in (d.get("componentSets") or {}).items():
            for v in (s.get("variants") or {}).values():
                comp_open.setdefault(name, set()).update(_rows_pairs(v.get("rows") or [], pairs, {}))
    for d in docs:
        if d.get("componentSets"):
            continue
        blocks = []

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "rows" and isinstance(v, list) and all(isinstance(x, str) for x in v):
                        blocks.append(v)
                    else:
                        walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
        for rows in blocks:
            _rows_pairs(rows, pairs, comp_open)
    return pairs


def check(cfg_path):
    if not cfg_path.exists():
        return 2, [f"設定がありません: {cfg_path}",
                   '  例: {"variables": "figma/variables.json", "frames": ["figma/frames.json", "figma/components.json"], '
                   '"css": ["../site/*.css"], "allow": {}}']
    try:
        conf = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return 2, [f"設定が読めません: {cfg_path}: {e}"]
    base = cfg_path.resolve().parent
    vpath = base / conf.get("variables", "")
    if not conf.get("variables") or not vpath.is_file():
        return 2, [f"**変数の書き出しがありません**: {vpath}"]
    variables = load_variables(vpath)
    table, from_names = role_usage(variables)
    if not table:
        return 2, [f"**色の役割が1つも分かりません**（色の変数 {len(variables)} 件。scopes も役割の名前も無い）"]
    by_css = {}
    for name in variables:
        role = name.split("/")[0].strip().lower()
        if role in table:
            by_css[css_name(name)] = role
    css_files = []
    for pat in conf.get("css") or []:
        css_files += sorted(Path(x) for x in glob.glob(str(base / pat), recursive=True))
    css_files = [f for f in css_files if f.is_file()]
    if not css_files:
        return 2, [f"**CSS が1つも見つかりません**: {conf.get('css')}"]
    pairs = figma_pairs([base / p for p in conf.get("frames") or []]) if conf.get("frames") else None
    if pairs is not None and not pairs:
        return 2, ["**Figma の書き出しから、文字色と面の組み合わせが1つも取れません。**"
                   "組み合わせを確かめられません（frames の指定を見直す）"]
    allow = conf.get("allow") or {}

    bad, used, waived, checked_pairs = [], 0, 0, 0
    for f in css_files:
        text = COMMENT_RX.sub(lambda m: " " * len(m.group(0)), f.read_text(encoding="utf-8", errors="ignore"))
        for m in RULE_RX.finditer(text):
            sel = m.group(1).strip()
            if not sel or sel.startswith("@"):
                continue
            lead = len(m.group(1)) - len(m.group(1).lstrip())
            line = text[:m.start(1) + lead].count("\n") + 1
            found = {}
            problems = []
            for decl in m.group(2).split(";"):
                prop, _, val = decl.partition(":")
                prop = prop.strip().lower()
                base_usage = PROP_USAGE.get(prop)
                if not base_usage:
                    continue
                # 影は1つずつ読む（縁取りだけの影は線）
                parts = re.split(r",(?![^()]*\))", val) if prop == "box-shadow" else [val]
                for part in parts:
                    usage = base_usage
                    if prop == "box-shadow" and RING_RX.match(part.strip()):
                        usage = "stroke"
                    uses = usage if isinstance(usage, set) else {usage}
                    for tok in VAR_RX.findall(part):
                        role = by_css.get(tok)
                        if not role:
                            continue
                        used += 1
                        for u in sorted(uses & table[role]):
                            found.setdefault(u, tok)
                        if not uses & table[role]:
                            ok = "・".join(USAGE_JA[u] for u in sorted(table[role]))
                            ja = "・".join(USAGE_JA[u] for u in sorted(uses))
                            problems.append(f"{prop}: var({tok}) は {ok}用（{ja}に使っている）")
            if pairs is not None and "text" in found and "surface" in found:
                checked_pairs += 1
                if (found["text"], found["surface"]) not in pairs:
                    problems.append(f"var({found['text']}) を var({found['surface']}) の上に置く組み合わせは Figma にありません")
            for p in problems:
                key = f"{f.name}:{sel}"
                if key in allow and str(allow[key]).strip():
                    waived += 1
                elif key in allow:
                    bad.append(f"  {f.name}:{line}  `{sel}`  {p}  ← **宣言に理由がありません**")
                else:
                    bad.append(f"  {f.name}:{line}  `{sel}`  {p}")
    head = (f"色の役割: 役割 {len(table)}（" + "・".join(f"{r}={'/'.join(sorted(u))}" for r, u in sorted(table.items()))
            + f"）・CSS {len(css_files)} 本・トークンの使用 {used} 件"
            + (f"・組み合わせの表 {len(pairs)} 組・同じ規則で見た組 {checked_pairs}" if pairs is not None
               else "・**組み合わせは見ていません**（frames が無い）")
            + f"・宣言つき {waived} 件")
    if from_names:
        head += f"\n  **scopes が書き出しに無いので、役割の名前から用途を導きました**: {', '.join(from_names)}"
    if used == 0:
        return 2, [head, "**役割の分かるトークンの使用が 0 件です。**0 件は「合っている」ではなく「見ていない」です"]
    if bad:
        return 1, ["**Figma が決めた用途・組み合わせと違う色の使い方があります:**", *bad,
                   "  直し方: 用途に合う役割のトークンを使う。Figma に無い組み合わせが要るなら、Figma に足してもらう",
                   f"  （Figma に無いのが正しいなら {cfg_path.name} の allow に「ファイル名:セレクタ」と理由を書く）", head]
    return 0, [head, "  用途も組み合わせも Figma どおりです"]


#: Flutter の書き方ごとに受ける用途。丸などの図形も BoxDecoration で描くので、面は図形も受ける
#: （2026-11-03 aub に当てて、手書きの規則より1件多く当たった原因）
FLUTTER_ACCEPT = {"text": {"text"}, "surface": {"surface", "shape"}, "stroke": {"stroke"}, "effect": {"effect"}}


def flutter_rules(variables, klass="AppColor"):
    table, from_names = role_usage(variables)
    rules = []
    for usage, shape in FLUTTER_SHAPES.items():
        accept = FLUTTER_ACCEPT[usage]
        ok_roles = sorted(r for r, u in table.items() if u & accept)
        bad_roles = sorted(r for r, u in table.items() if not u & accept)
        if not ok_roles or not bad_roles:
            continue
        rules.append({
            "id": f"scope-generated-{usage}",
            "pattern": shape + rf"{klass}\.(?:{'|'.join(camel(r) for r in bad_roles)})(?=[A-Z])",
            "severity": "error",
            "forbidden": f"{USAGE_JA[usage]}に、{USAGE_JA[usage]}用でないトークン（{', '.join(bad_roles)}）を使う（Figma の用途から生成）",
            "instead": f"{USAGE_JA[usage]}には {', '.join(ok_roles)} の役割のトークンを使う",
            "_selftest": {
                "bad": [FLUTTER_EXAMPLES[usage].format(c=f"{klass}.{camel(r)}NeutralDefault") for r in bad_roles],
                "good": [FLUTTER_EXAMPLES[usage].format(c=f"{klass}.{camel(r)}NeutralDefault") for r in ok_roles],
            },
        })
    return rules, from_names


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
        (root / "figma").mkdir()
        var = {"collections": {"ColorSemantic": {"variables": [
            {"name": "Frame/Neutral/Default", "type": "COLOR", "scopes": ["FRAME_FILL"]},
            {"name": "Frame/Inverse/Default", "type": "COLOR", "scopes": ["FRAME_FILL"]},
            {"name": "Text/Neutral/Default", "type": "COLOR", "scopes": ["TEXT_FILL"]},
            {"name": "Text/Inverse/Default", "type": "COLOR", "scopes": ["TEXT_FILL"]},
            {"name": "Stroke/Neutral/Default", "type": "COLOR", "scopes": ["STROKE_COLOR"]},
            {"name": "Gap/M", "type": "FLOAT", "scopes": ["GAP"]}]}}}
        (root / "figma" / "variables.json").write_text(json.dumps(var), encoding="utf-8")
        (root / "figma" / "frames.json").write_text(json.dumps({"frames": {"1:1": {"rows": [
            "0|Page|FRAME|100|100|0|0|fill=Frame/Neutral/Default",
            "1|Title|TEXT|10|10|0|0|fill=Text/Neutral/Default",
            "1|Band|FRAME|100|10|0|20|fill=Frame/Inverse/Default",
            "2|Label|TEXT|10|10|0|0|fill=Text/Inverse/Default"]}}}), encoding="utf-8")
        (root / "figma" / "components.json").write_text(json.dumps({"componentSets": {"Card": {"variants": {
            "Type=A": {"rows": ["0|Type=A|COMPONENT|10|10|0|0", "1|Name|TEXT|5|5|0|0|fill=Text/Inverse/Default"]}}}}}),
            encoding="utf-8")
        (root / "figma" / "frames2.json").write_text(json.dumps({"frames": {"2:2": {"rows": [
            "0|Modal|FRAME|100|100|0|0|fill=Frame/Inverse/Default",
            "1|Card|INSTANCE|10|10|0|0|of=Card/Type=A"]}}}), encoding="utf-8")
        ck(("--text-inverse-default", "--frame-inverse-default") in
           figma_pairs([root / "figma" / "components.json", root / "figma" / "frames2.json"]),
           "部品の中の文字と、部品を置いた面の組を数えていない")
        css = root / "site.css"
        cfg = root / "token-roles.json"

        def run(text, allow=None, frames=True):
            css.write_text(text, encoding="utf-8")
            c = {"variables": "figma/variables.json", "css": ["site.css"], "allow": allow or {}}
            if frames:
                c["frames"] = ["figma/frames.json"]
            cfg.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
            return check(cfg)

        good = (".a{color:var(--text-neutral-default);background:var(--frame-neutral-default)}\n"
                ".b{color:var(--text-inverse-default);background:var(--frame-inverse-default);"
                "border:1px solid var(--stroke-neutral-default)}\n")
        rc, out = run(good)
        ck(rc == 0, f"Figma どおりの使い方を落とした: {rc} {out}")
        rc, out = run(".a{background:var(--text-neutral-default)}\n")
        ck(rc == 1 and any("面に使っている" in x for x in out), f"**文字用の色を面に使ったのを通した**: {rc} {out}")
        rc, out = run(".a{box-shadow:inset 0 0 0 1px var(--stroke-neutral-default)}\n"
                      ".c{box-shadow:inset 0 0 0 var(--stroke-s) var(--stroke-neutral-default)}\n"
                      ".d{box-shadow:0 0 0 calc(var(--stroke-s) / 2) var(--stroke-neutral-default)}\n"
                      ".b{stroke:var(--stroke-neutral-default)}\n", frames=False)
        ck(rc == 0, f"縁取りだけの影・SVG の線に線の色を使うのを落とした: {rc} {out}")
        rc, out = run(".a{box-shadow:0 4px 8px var(--stroke-neutral-default)}\n", frames=False)
        ck(rc == 1, f"**ぼかしのある影に線の色を使ったのを通した**: {rc}")
        rc, out = run(".a{color:var(--frame-neutral-default)}\n", frames=False)
        ck(rc == 1, f"**面の色を文字に使ったのを通した**: {rc}")
        rc, out = run(".a{border-color:var(--frame-neutral-default)}\n")
        ck(rc == 1, f"**面の色を線に使ったのを通した**: {rc}")
        rc, out = run(".a{color:var(--text-inverse-default);background:var(--frame-neutral-default)}\n")
        ck(rc == 1 and any("Figma にありません" in x for x in out), f"**表に無い組み合わせを通した**: {rc} {out}")
        rc, _ = run(".a{color:var(--text-inverse-default);background:var(--frame-neutral-default)}\n",
                    {"site.css:.a": "ダークの帯の試作。Figma に足すまでの間"})
        ck(rc == 0, f"理由つきの宣言を落とした: {rc}")
        rc, out = run(".a{color:var(--text-inverse-default);background:var(--frame-neutral-default)}\n",
                      {"site.css:.a": ""})
        ck(rc == 1 and any("理由がありません" in x for x in out), f"**理由の無い宣言を通した**: {rc}")
        rc, out = run(good, frames=False)
        ck(rc == 0 and any("組み合わせは見ていません" in x for x in out), f"frames が無いのに、見ていないと言わない: {out}")
        rc, _ = run("/* .x{background:var(--text-neutral-default)} */ .a{color:var(--text-neutral-default)}\n")
        ck(rc == 0, f"コメントの中を数えた: {rc}")
        rc, out = run(".a{padding:var(--gap-m)}\n")
        ck(rc == 2, f"役割のトークンの使用が 0 件なのに 2 でない: {rc}")

        # scopes の無い書き出し（aub・414）は、役割の名前から導き、そう言う
        (root / "figma" / "variables.json").write_text(json.dumps({"collections": [{"name": "ColorSemantic",
            "variables": [{"name": "Frame/Neutral/Default", "type": "COLOR"},
                          {"name": "Text/Neutral/Default", "type": "COLOR"}]}]}), encoding="utf-8")
        rc, out = run(".a{background:var(--text-neutral-default)}\n", frames=False)
        ck(rc == 1 and any("名前から用途を導きました" in x for x in out), f"名前から導いたと言わない: {rc} {out}")
        # 414 の rows 形式
        (root / "figma" / "v414.json").write_text(json.dumps({"variables": {"ColorSemantic": {"rows": [
            {"n": "Frame/Neutral/Default", "v": {}}, {"n": "Text/Neutral/Default", "v": {}}]},
            "Gap": {"rows": [{"n": "M", "v": 8}]}}}), encoding="utf-8")
        v414 = load_variables(root / "figma" / "v414.json")
        ck(sorted(v414) == ["Frame/Neutral/Default", "Text/Neutral/Default"], f"414 の形式を読めない: {v414}")

        # Flutter 向けの規則の生成
        rules, _ = flutter_rules(v414)
        surf = next((r for r in rules if r["id"] == "scope-generated-surface"), None)
        ck(surf is not None and re.search(surf["pattern"], "BoxDecoration(color: AppColor.textNeutralDefault)")
           and not re.search(surf["pattern"], "BoxDecoration(color: AppColor.frameNeutralDefault)"),
           f"生成した Flutter の規則が当たらない・当たりすぎる: {surf}")
        # 生成物は仕込みを持ち、それぞれが当たる・当たらない（#180）
        for r in rules:
            st = r.get("_selftest") or {}
            ck(st.get("bad") and st.get("good")
               and all(re.search(r["pattern"], s) for s in st["bad"])
               and not any(re.search(r["pattern"], s) for s in st["good"]),
               f"生成した規則の仕込みが無いか、当たり方が違う: {r['id']} {st}")
        out_json = root / "scope.generated.json"
        cfg.write_text(json.dumps({"variables": "figma/v414.json"}), encoding="utf-8")
        ck(main(["--config", str(cfg), "--emit-flutter", str(out_json)]) == 0 and out_json.exists(), "生成できない")
        ck(main(["--config", str(cfg), "--check-flutter", str(out_json)]) == 0, "生成した直後なのに古いと言った")
        (root / "figma" / "v414.json").write_text(json.dumps({"variables": {"ColorSemantic": {"rows": [
            {"n": "Frame/Neutral/Default", "v": {}}, {"n": "Text/Neutral/Default", "v": {}},
            {"n": "Stroke/Neutral/Default", "v": {}}]}}}), encoding="utf-8")
        ck(main(["--config", str(cfg), "--check-flutter", str(out_json)]) == 1, "**Figma が変わったのに生成物が古いと言わない**")
        ck(main(["--config", str(cfg), "--check-flutter", str(root / "none.json")]) == 2, "生成物が無いのに 2 でない")

        ck(main(["--config", str(root / "no.json")]) == 2, "設定が無いのに 2 でない")
        cfg.write_text(json.dumps({"variables": "figma/variables.json", "css": ["site.css"]}), encoding="utf-8")
        css.write_text(".a{background:var(--text-neutral-default)}\n", encoding="utf-8")
        ck(main(["--config", str(cfg)]) == 1, "入口が用途違いで 1 を返さない")
        css.write_text(".a{color:var(--text-neutral-default)}\n", encoding="utf-8")
        ck(main(["--config", str(cfg)]) == 0, "入口が合っているのに 0 を返さない")

    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="色のトークンを Figma の用途と組み合わせで使っているか")
    ap.add_argument("--config", type=Path, default=Path("design/token-roles.json"))
    ap.add_argument("--emit-flutter", type=Path, help="Flutter 向けの用途の規則を生成して書く")
    ap.add_argument("--check-flutter", type=Path, help="生成した Flutter の規則が Figma と合っているか")
    ap.add_argument("--flutter-class", default="AppColor")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.emit_flutter or a.check_flutter:
        try:
            conf = json.loads(a.config.read_text(encoding="utf-8"))
            variables = load_variables(a.config.resolve().parent / conf["variables"])
        except (OSError, KeyError, json.JSONDecodeError) as e:
            print(f"変数の書き出しが読めません: {e}", file=sys.stderr)
            return 2
        rules, from_names = flutter_rules(variables, a.flutter_class)
        if not rules:
            print("色の役割が分からず、規則を作れません（確かめられなかった）", file=sys.stderr)
            return 2
        doc = {"$meta": {"generated_by": "design/harness/tools/token_role_check.py --emit-flutter",
                         "note": "手で直さない。Figma の変数を書き出し直したら作り直す",
                         "roles_from_names": from_names},
               "rules": rules}
        text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        if a.emit_flutter:
            a.emit_flutter.write_text(text, encoding="utf-8")
            print(f"Flutter の用途の規則を {len(rules)} 本作りました: {a.emit_flutter}")
            return 0
        if not a.check_flutter.is_file():
            print(f"生成物がありません: {a.check_flutter}", file=sys.stderr)
            return 2
        if a.check_flutter.read_text(encoding="utf-8") != text:
            print(f"**生成物が Figma の変数と合っていません**（古い）: {a.check_flutter}。--emit-flutter で作り直す", file=sys.stderr)
            return 1
        print(f"生成物は Figma の変数と合っています: {a.check_flutter}")
        return 0
    rc, lines = check(a.config)
    for x in lines:
        print(x, file=sys.stderr if rc else sys.stdout)
    if rc == 2:
        return 2
    if rc != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
