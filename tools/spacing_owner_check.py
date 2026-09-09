#!/usr/bin/env python3
"""**余白・寸法のトークンを持つ実装要素は、対応表の Figma ノードに対応していること**（#108）。

## 実害（QnD・2026-09-09・**ユーザーが目視で発見。機械は全部緑だった**）

戻る矢印の上端が、事例詳細 183px に対して **PoV 詳細 243px**（60px ずれ）。
Figma はどちらのページも同じ（`Frame 52` V gap120 pad60/0）。
PoV 詳細だけ、実装が `main.page` の**内側に** `.pov-page.is-single` を置き、
**両方が上 60 を持っていた**（どちらも `var(--gap-xxl)`）。

- 各要素は単体で Figma と一致 → 値の照合は緑（100組293値・不一致0）
- トークン名で照合しても緑（外も内も同じトークンを参照している）
- **Figma に対応が無い余分な器が、余白トークンを持っていた**のが実体

## 座標では解かない

「ページの上から何px か」は却下（ユーザー指摘）。QnD は余白を画面幅に比例させる
（`clamp`）ので、座標は幅ごとに変わり**偽の不一致が大量に出る**。

## 見るもの

    余白・すき間・寸法のトークン（`var(--gap-…)` `var(--pad-…)` …）を
    余白系のプロパティに持つ CSS の規則は、その主語が
    **対応表（screen-map の sel ／ components の impl）のどれかに対応していること。**

**対応の無い要素がそれらを持っていたら赤。** 座標に依存せず、fluid な値でも成り立つ。

## 照合の決まり（#106 の教訓をそのまま使う）

- **主語（一番右の複合セレクタ）で見る。** 子孫の規則で通さない
- **疑似クラス・疑似要素は無視する**（`.list-row:hover` は `.list-row` と同じ要素）
- **追加クラスは別の要素。** `.pov-page.is-single` は `.pov-page` と**同じではない**。
  ここを緩めると、まさに 60px の二重掛けが通る
- **対応づけられた部品の中は見ない。** `.footer .links` の主語は対応表に無いが、
  祖先 `.footer` が部品として対応づけられている。部品の中身は部品の責任
  （値の照合は screen-spec 側）。**ただし同じ要素への追加クラスは救わない**

## 分母を出す

**走査した CSS のファイル数・規則の数・トークンを持つ規則の数・対応表の要素数**を必ず出す。
**0 件は「揃っている」ではなく「見ていない」**なので、どれかが 0 なら 2 で止まる。

## 終了コード

    0  対応の無い持ち主は無い（宣言つきは除く）
    1  対応の無い持ち主がある／宣言に理由が無い
    2  **確かめられなかった**（設定・対応表・CSS が無い、トークンを持つ規則が 0）
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401

#: 余白・すき間・寸法のプロパティ
SPACING_PROPS = ("padding", "margin", "gap", "row-gap", "column-gap", "inset",
                 "top", "right", "bottom", "left",
                 "width", "height", "min-width", "max-width", "min-height", "max-height")
#: トークン名の頭。案件の設定で足せる
DEFAULT_TOKENS = ("--gap-", "--pad-", "--space-", "--size-")
BLOCK_COMMENT_RX = re.compile(r"/\*.*?\*/", re.S)
RULE_RX = re.compile(r"([^{}]+)\{([^{}]*)\}")
PSEUDO_RX = re.compile(r"::?[a-zA-Z-]+(?:\([^)]*\))?")
COMBINATOR_RX = re.compile(r"\s*[>+~]\s*|\s+")


def compounds(selector):
    """1つのセレクタを複合セレクタの列に割る（左→右）。疑似クラスは落とす。"""
    parts = [p for p in COMBINATOR_RX.split(selector.strip()) if p]
    return [PSEUDO_RX.sub("", p) for p in parts]


def normalize(compound):
    """複合セレクタを比べられる形に。`a.b.c` → 要素名 + クラスの集合（順不同）。"""
    compound = PSEUDO_RX.sub("", compound.strip())
    m = re.match(r"^([a-zA-Z][\w-]*|\*)?(.*)$", compound)
    tag = (m.group(1) or "").lower()
    rest = m.group(2)
    classes = frozenset(re.findall(r"\.([\w-]+)", rest))
    attrs = frozenset(re.findall(r"\[[^\]]*\]", rest))
    ids = frozenset(re.findall(r"#([\w-]+)", rest))
    return (tag, classes, ids, attrs)


def spacing_declared(body, tokens):
    """規則の中身に、余白系のプロパティ × トークンの組があるか。あればその宣言を返す。"""
    out = []
    for decl in body.split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop = prop.strip().lower()
        base = prop.split("-")[0] if prop.startswith(("padding-", "margin-", "inset-")) else prop
        if (prop in SPACING_PROPS or base in SPACING_PROPS) and any(t in val for t in tokens):
            out.append(f"{prop}:{val.strip()}")
    return out


def load_owners(cfg_dir, conf):
    """対応表から、対応づけられた要素（正規化した複合セレクタ）を集める。"""
    owners = {}   # normalized → 由来
    roots = set()  # 部品の根（この中は見ない）
    sm = conf.get("screenMap")
    if sm:
        p = (cfg_dir / sm).resolve()
        if not p.exists():
            return None, f"対応表がありません: {p}"
        d = json.loads(p.read_text(encoding="utf-8"))
        for key, v in (d.get("map") or {}).items():
            sel = v.get("sel") if isinstance(v, dict) else None
            if not sel:
                continue
            for one in str(sel).split(","):
                cs = compounds(one)
                if cs:
                    owners[normalize(cs[-1])] = f"screen-map: {key}"
    cm = conf.get("componentMap")
    if cm:
        p = (cfg_dir / cm).resolve()
        if not p.exists():
            return None, f"部品の対応表がありません: {p}"
        d = json.loads(p.read_text(encoding="utf-8"))
        comps = d.get("components") or {}
        items = comps.items() if isinstance(comps, dict) else \
            ((c.get("figma"), c) for c in comps if isinstance(c, dict))
        for name, v in items:
            impl = v.get("impl") if isinstance(v, dict) else None
            sels = []
            if isinstance(impl, str):
                sels = [s.strip().split()[0] for s in impl.split("/") if s.strip()]
            elif isinstance(impl, list):
                sels = [x.get("class") for x in impl if isinstance(x, dict) and x.get("class")]
            for s in sels:
                n = normalize(s)
                owners[n] = f"components: {name}"
                roots.add(n)
    return (owners, roots), None


def check(cfg_path: Path):
    """`(終了コード, 行の一覧)`。"""
    if not cfg_path.exists():
        return 2, [f"設定がありません: {cfg_path}",
                   '  例: {"screenMap": "values/screen-map.json", '
                   '"componentMap": "values/components.json", '
                   '"css": ["../../styles/shared.css"], "allow": {}}',
                   "  **余白トークンの持ち主を、誰も見ていない状態です。**"]
    try:
        conf = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return 2, [f"設定が読めません: {cfg_path}: {e}"]
    cfg_dir = cfg_path.resolve().parent
    tokens = tuple(conf.get("tokens") or DEFAULT_TOKENS)
    allow = conf.get("allow") or {}

    loaded, err = load_owners(cfg_dir, conf)
    if err:
        return 2, [f"**{err}**", "  対応表が無ければ、対応の有無を確かめられません"]
    owners, roots = loaded
    if not owners:
        return 2, ["**対応表に要素が1つもありません。**分母が無いので確かめられません"]

    css_files = []
    for pat in conf.get("css") or []:
        css_files += [Path(x) for x in sorted(glob.glob(str((cfg_dir / pat).resolve()), recursive=True))]
    css_files = [f for f in css_files if f.is_file()]
    if not css_files:
        return 2, [f"**CSS が1つも見つかりません**: {conf.get('css')}（{cfg_dir} から）"]

    n_rules = 0
    carriers = []   # (file, line, selector, decls)
    for f in css_files:
        text = BLOCK_COMMENT_RX.sub(lambda m: " " * len(m.group(0)), f.read_text(encoding="utf-8", errors="ignore"))
        for m in RULE_RX.finditer(text):
            head, body = m.group(1).strip(), m.group(2)
            if not head or head.startswith("@"):
                continue
            n_rules += 1
            decls = spacing_declared(body, tokens)
            if not decls:
                continue
            line = text[:m.start()].count("\n") + 1
            for one in head.split(","):
                one = one.strip()
                if one:
                    carriers.append((f, line, one, decls))
    if not carriers:
        return 2, [f"**余白・寸法のトークンを持つ規則が 0 件です**（CSS {len(css_files)} 本・規則 {n_rules} 本）。",
                   "  **0 件は「揃っている」ではなく「見ていない」です。**"
                   "トークンの頭（tokens）が案件の名前と合っているか確かめてください"]

    bad, waived, lines = [], 0, []
    for f, line, sel, decls in carriers:
        cs = compounds(sel)
        if not cs:
            continue
        subj = normalize(cs[-1])
        if subj in owners:
            continue
        # 対応づけられた部品の**中**（祖先が部品の根）は部品の責任
        if any(normalize(c) in roots for c in cs[:-1]):
            continue
        key = sel
        if key in allow:
            why = str(allow[key]).strip()
            if not why:
                bad.append((f, line, sel, decls, "**宣言に理由がありません**"))
            else:
                waived += 1
            continue
        bad.append((f, line, sel, decls, None))

    head = (f"余白の持ち主: CSS {len(css_files)} 本・規則 {n_rules} 本・"
            f"トークンを持つ規則 {len(carriers)} 本・対応表の要素 {len(owners)} 件"
            f"（うち部品の根 {len(roots)}）・宣言つき {waived} 件")
    if bad:
        lines.append("**Figma に対応の無い要素が、余白・寸法のトークンを持っています:**")
        for f, line, sel, decls, note in bad:
            rel = f.name if len(css_files) == 1 else str(f)
            lines.append(f"  {rel}:{line}  `{sel}`  {'; '.join(decls)[:80]}" + (f"  ← {note}" if note else ""))
        lines += [
            "  **値は全部正しくても、積み上がりが違う形です**（QnD で 60px ずれた）。",
            "  直し方は3つ: (1) その要素を対応表（screen-map の sel）に結ぶ",
            "  (2) 余白を、対応づけられた要素へ移す  (3) Figma に無いのが正しいなら",
            f"  `{cfg_path.name}` の allow に**理由つきで**宣言する（理由の無い宣言は落とします）",
            f"  {head}",
        ]
        return 1, lines
    return 0, [head, "  対応の無い持ち主はありません"]


def self_test():
    """**60px の二重掛けの形で落ちること**が本体（妨害テスト）。"""
    import tempfile
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "values").mkdir()
        (root / "values" / "screen-map.json").write_text(json.dumps({"map": {
            "Pov_Single/Frame 52": {"sel": "main.page", "page": "pov-single"},
            "Pov_Collection/Frame 52": {"sel": ".pov-page", "page": "pov-list"},
            "Case/Frame 53": {"sel": "main.page > section.block:nth-of-type(1)", "page": "case"},
        }}, ensure_ascii=False), encoding="utf-8")
        (root / "values" / "components.json").write_text(json.dumps({"components": {
            "Footer": {"impl": ".footer"},
            "Lists": {"impl": ".lists / .list-row / .slot-left"},
        }}, ensure_ascii=False), encoding="utf-8")
        css = root / "shared.css"
        cfg = root / "spacing-owners.json"

        def run(css_text, allow=None):
            css.write_text(css_text, encoding="utf-8")
            cfg.write_text(json.dumps({"screenMap": "values/screen-map.json",
                                       "componentMap": "values/components.json",
                                       "css": ["shared.css"], "allow": allow or {}},
                                      ensure_ascii=False), encoding="utf-8")
            return check(cfg)

        # 1) **60px の二重掛け**: 対応の無い `.pov-page.is-single` が余白トークンを持つ → 落ちる
        rc, out = run("main.page{padding:var(--gap-xxl) 0}\n"
                      ".pov-page.is-single{padding:var(--gap-xxl) var(--pad-side)}\n")
        ck(rc == 1, f"**二重掛けを通した**: {rc}")
        ck(any(".pov-page.is-single" in x for x in out), f"どの要素かを名指ししていない: {out}")

        # 2) 直したあと（余白は 0 でトークンを持たない） → 通る
        rc, _ = run("main.page{padding:var(--gap-xxl) 0}\n.pov-page.is-single{padding:0}\n")
        ck(rc == 0, f"直した形を落とした: {rc}")

        # 3) **追加クラスは別の要素**（`.pov-page` が対応づけられていても救わない）
        rc, _ = run(".pov-page.is-single{gap:var(--gap-xl)}\n")
        ck(rc == 1, f"**追加クラスを同じ要素と見た**（ここを緩めると二重掛けが通る）: {rc}")

        # 4) 疑似クラスは無視 → `.list-row:hover` は `.list-row`（部品）→ 通る
        rc, _ = run(".list-row:hover{gap:var(--gap-col)}\n")
        ck(rc == 0, f"疑似クラスで別の要素と見た: {rc}")

        # 5) 部品の中（`.footer .links`）は部品の責任 → 通る
        rc, _ = run(".footer .links{gap:var(--gap-s)}\n")
        ck(rc == 0, f"部品の中身を咎めた: {rc}")

        # 6) 子孫の規則で救わない: `.pov-page .stray` の主語 `.stray` は対応が無く、祖先 `.pov-page` は部品でない → 落ちる
        rc, _ = run(".pov-page .stray{padding:var(--gap-s)}\n")
        ck(rc == 1, f"**画面の中の対応の無い要素を、祖先で救った**: {rc}")

        # 7) 対応表の複雑なセレクタ（`main.page > section.block:nth-of-type(1)`）と一致 → 通る
        rc, _ = run("main.page > section.block:nth-of-type(1){padding:var(--gap-block) 0}\n")
        ck(rc == 0, f"複雑な対応先と一致しない: {rc}")

        # 8) 宣言（理由つき）→ 通る／理由なし → 落ちる
        rc, _ = run(".inset{padding-left:var(--pad-side)}\n", {".inset": "左右の余白だけを与える補助クラス。Figma に器は無い"})
        ck(rc == 0, f"理由つきの宣言を落とした: {rc}")
        rc, out = run(".inset{padding-left:var(--pad-side)}\n", {".inset": ""})
        ck(rc == 1 and any("理由がありません" in x for x in out), f"**理由の無い宣言を通した**: {rc}")

        # 9) 余白でないトークン（色）は数えない → 持ち主 0 → **2**
        rc, out = run(".x{color:var(--text-neutral-default)}\n")
        ck(rc == 2, f"トークンを持つ規則が 0 なのに 2 でない: {rc}")

        # 10) コメントの中は数えない
        rc, _ = run("/* .ghost{padding:var(--gap-xxl)} */\nmain.page{padding:var(--gap-xxl) 0}\n")
        ck(rc == 0, f"コメントの中の規則を数えた: {rc}")

        # 11) 対応表が無い → 2
        (root / "values" / "screen-map.json").unlink()
        rc, _ = run("main.page{padding:var(--gap-xxl) 0}\n")
        ck(rc == 2, f"対応表が無いのに 2 でない: {rc}")

        # 12) **入口（main）まで通す。** check() だけを見ていると、入口の落とす帰り道が
        # 一度も走らない（変異試験が「理由なしの素通り 2 件」として出した・2026-09-10）
        import contextlib, io
        def via_main(cfg_path):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                return main(["--config", str(cfg_path)])
        ck(via_main(cfg) == 2, "入口が対応表なしで 2 を返さない")
        (root / "values" / "screen-map.json").write_text(json.dumps({"map": {
            "Pov_Single/Frame 52": {"sel": "main.page"}}}), encoding="utf-8")
        css.write_text(".pov-page.is-single{padding:var(--gap-xxl)}\n", encoding="utf-8")
        ck(via_main(cfg) == 1, "入口が二重掛けで 1 を返さない")
        css.write_text("main.page{padding:var(--gap-xxl) 0}\n", encoding="utf-8")
        ck(via_main(cfg) == 0, "入口が揃っているのに 0 を返さない")

    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="余白トークンの持ち主が Figma に対応しているか")
    ap.add_argument("--config", type=Path, default=Path("design/spacing-owners.json"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
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
