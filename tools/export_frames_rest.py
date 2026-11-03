#!/usr/bin/env python3
"""**画面の書き出しを Figma の REST API から作る**（#179・2026-11-03）。

`exporters/export_frames.js`（Figma の中で動く器）と**同じ行の形**を、REST の nodes から作る。
use_figma の1回の戻り（約18KB）を通らないので、**大きい画面も会話に書き写さずにファイルへ直接書ける。**

実害（2026-11-03・FlashEnglish）: 1画面 23〜75KB・17節で約 2.8MB あり、Figma の中の器を分けて
呼んで frame_io.py でつなぐと、書き写す量が 2.8MB になって現実的でなかった（#170 は「つなぐ」は
解いたが「量」は解いていなかった）。

## 器との違い（REST で取れないもの）

- **部品の上書きで、効果のスタイルだけを替えたのか、効果の中身も替えたのか**は区別できない（REST はどちらも
  `effects` と言う）。この道具は両方（`effectStyleId` と `effects`）を挙げる。器は片方だけのことがある
  （portfolio の 23 画面で 2 行。2026-11-03 実測）

- **変数は REST では ID しか返らない**（Variables の REST は Enterprise 限定）。`--variables` に
  Variables の書き出し（export_variables.js の出力。**2026-11-03 から id と key を書く**）を渡し、
  その対応表で名前に引く。ライブラリの変数（`VariableID:<key>/…`）は key で引く。引けなければ `?` と書き、
  `$meta.読めなかったもの` に並べる（黙って直値にしない）
- 回転した節点の幅・高さは、REST の外接矩形で書く（器は回転前の寸法。回転が無ければ同じ）
- ライブラリの部品の定義の寸法は取れないので、`override=` は書かず `読めなかったもの` に並べる

**器と1字まで同じになるか**は、`--compare <器の書き出し>` で行ごとに比べる。

## 使い方

    export_frames_rest.py --file <fileKey> --page <ページ名> --section <節の名前> [--section …]
                          --width <版面の幅> --variables <variables.json> [--variables …] --out frames.json
    export_frames_rest.py --file <fileKey> --ids 1:2,3:4 --variables … --out frames.json
    export_frames_rest.py --compare <器の frames.json> <この道具の frames.json>

FIGMA_TOKEN が要る（環境から読む。値は表示しない）。

## 終了コード

    0  書き出した（--compare: 全行一致）
    1  --compare: 違う行がある
    2  確かめられなかった（鍵が無い・応答が読めない・対象0件・変数の対応表が無い）
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401

API = "https://api.figma.com/v1"
CONSTRAINT = {"LEFT": "MIN", "TOP": "MIN", "RIGHT": "MAX", "BOTTOM": "MAX", "CENTER": "CENTER",
              "LEFT_RIGHT": "STRETCH", "TOP_BOTTOM": "STRETCH", "SCALE": "SCALE"}
#: 差し込み口（SLOT）も枠と同じ欄を持つ（2026-11-03 器の行で確かめた）
FRAMELIKE = {"FRAME", "INSTANCE", "COMPONENT", "COMPONENT_SET", "SECTION", "SLOT"}
#: 器（Plugin API）がその型で値を持つ欄。持たない欄は書かない（器と同じ）
HAS_CLIP = FRAMELIKE
HAS_SIDES = FRAMELIKE | {"RECTANGLE"}
NO_STROKE = {"GROUP"}
CORNERS = ("RECTANGLE_TOP_LEFT_CORNER_RADIUS", "RECTANGLE_TOP_RIGHT_CORNER_RADIUS",
           "RECTANGLE_BOTTOM_RIGHT_CORNER_RADIUS", "RECTANGLE_BOTTOM_LEFT_CORNER_RADIUS")
SKIP_OV = {"name", "x", "y", "relativeTransform", "pluginData", "autoRename", "expanded"}
TEXT_VAR_KEYS = {"fontSize", "lineHeight", "fontName", "fontFamily", "fontStyle", "fontWeight"}
#: REST が省く既定値（器は既定値を返す）。上書きの欄の値を器と同じにするため
OV_DEFAULT = {"primaryAxisSizingMode": "AUTO", "counterAxisSizingMode": "AUTO", "primaryAxisAlignItems": "MIN",
              "counterAxisAlignItems": "MIN", "layoutMode": "NONE", "paddingTop": 0, "paddingRight": 0,
              "paddingBottom": 0, "paddingLeft": 0, "itemSpacing": 0, "opacity": 1, "visible": True,
              "layoutGrow": 0, "layoutAlign": "INHERIT", "clipsContent": False, "cornerRadius": 0,
              "strokeWeight": 1, "layoutPositioning": "AUTO", "layoutWrap": "NO_WRAP"}


def R(x):
    """器の `Math.round(x * 100) / 100` と同じ丸め（JS の書き方で数を文字にする）。"""
    if x is None:
        return None
    if isinstance(x, float) and math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    v = math.floor(x * 100 + 0.5) / 100
    return int(v) if v == int(v) else v


def js(v):
    """JSON.stringify と同じ書き方（区切りに空白を入れない・ASCII に逃がさない）。"""
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def num(v):
    """JS が数を文字にした形（1.0 → 1）。"""
    if isinstance(v, float) and v == int(v) and not math.isinf(v):
        return str(int(v))
    return str(v)


def esc(t):
    return t.replace("|", "\\u007c")


def safe(t):
    return "".join("\\u%04x" % ord(c) if c in "\u2028\u2029\u0085" else c for c in t)


def hexc(c, alpha=True):
    b = lambda x: "%02x" % int(math.floor(x * 255 + 0.5))
    a = c.get("a", 1) if alpha else 1
    return "#" + b(c["r"]) + b(c["g"]) + b(c["b"]) + ("" if a == 1 else b(a))


def fnv(s):
    """器の h() と同じ（JS の charCodeAt は UTF-16 の単位なので、絵文字は2つに割れる）。"""
    x = 0x811c9dc5
    b = s.encode("utf-16-le")
    for i in range(0, len(b), 2):
        x ^= b[i]
        x = (x + ((x << 1) + (x << 4) + (x << 7) + (x << 8) + (x << 24))) & 0xFFFFFFFF
    return x


class Ctx:
    def __init__(self, var_names, var_keys, styles, components, component_sets, comp_sizes, var_values=None,
                 mode_values=None):
        self.var_names, self.var_keys = var_names, var_keys
        self.var_values = var_values or {}
        self.mode_values = mode_values or {}
        self.styles, self.components, self.component_sets = styles, components, component_sets
        self.comp_sizes = comp_sizes
        self.not_read, self.seen = [], set()

    def miss(self, node, fields, why):
        k = (node.get("id"), tuple(fields), why)
        if k not in self.seen:
            self.seen.add(k)
            self.not_read.append({"instance": node.get("id"), "name": node.get("name"), "fields": list(fields), "why": why})

    def var(self, alias, node=None, field=""):
        e = alias[0] if isinstance(alias, list) and alias else alias
        if not isinstance(e, dict) or not e.get("id"):
            return None
        vid = e["id"]
        if vid in self.var_names:
            return self.var_names[vid]
        m = re.match(r"VariableID:([0-9a-f]{40})/", vid)
        if m and m.group(1) in self.var_keys:
            return self.var_keys[m.group(1)]
        if node is not None:
            self.miss(node, [field], f"変数 {vid} の名前が対応表にありません（--variables を足す）")
        return "?"

    def value(self, alias):
        e = alias[0] if isinstance(alias, list) and alias else alias
        return self.var_values.get(e.get("id")) if isinstance(e, dict) else None

    def values_any_mode(self, alias):
        """変数のすべてのモードの値。器は置かれた場所のモードで解決するので、どれかと一致すれば同じ扱いになる。"""
        e = alias[0] if isinstance(alias, list) and alias else alias
        if not isinstance(e, dict):
            return []
        vid = e.get("id")
        vals = list(self.mode_values.get(vid) or [])
        if vid in self.var_values and self.var_values[vid] not in vals:
            vals.append(self.var_values[vid])
        return vals

    def style(self, sid):
        s = self.styles.get(sid) if sid else None
        return s.get("name") if s else None


def bvars(n):
    """節点の boundVariables を器の欄の名前で返す。

    REST は幅・高さの変数を `size: {x, y}` で返し、器は `width`・`height` で返す（2026-11-03・414 で見つかった。
    アイコンの寸法が Width&Heights の変数に結ばれているのに、bind= と上書きから width・height が落ちていた）。
    器の boundVariables では width・height が先に来るので、先に置く
    """
    bv = n.get("boundVariables") or {}
    size_bv = bv.get("size") if isinstance(bv.get("size"), dict) else {}
    out = {}
    if size_bv.get("x"):
        out["width"] = size_bv["x"]
    if size_bv.get("y"):
        out["height"] = size_bv["y"]
    for k, v in bv.items():
        if k != "size":
            out[k] = v
    return out


def bn(ctx, n, f):
    bv = bvars(n).get(f)
    return ctx.var(bv, n, f) if bv else None


def paint_of(ctx, n, f):
    if f["type"] == "SOLID":
        bv = (f.get("boundVariables") or {}).get("color")
        return (ctx.var(bv, n, "fills") if bv else None) or ("SOLID:" + hexc(f["color"], alpha=False))
    if f["type"].startswith("GRADIENT"):
        st = []
        for g in f.get("gradientStops") or []:
            bv = (g.get("boundVariables") or {}).get("color")
            st.append(((ctx.var(bv, n, "fills") if bv else None) or hexc(g["color"])) + "@" + num(R(g["position"])))
        return f["type"] + ":" + ">".join(st)
    ref = f.get("imageRef")
    return f["type"] + (":" + ref[:8] if ref else "")


def fills_of(ctx, n):
    fl = n.get("fills")
    if not isinstance(fl, list) or not fl:
        return None
    vis = [f for f in fl if f.get("visible", True) is not False]
    if not vis:
        return None
    v = bn(ctx, n, "fills")
    if len(vis) == 1 and vis[0]["type"] == "SOLID" and v:
        return v
    return "+".join(paint_of(ctx, n, f) for f in vis)


def size(n):
    """器の width/height（回転の前の寸法）。REST は geometry=paths のとき size を返す。無ければ外接矩形"""
    s = n.get("size")
    if isinstance(s, dict):
        return s.get("x"), s.get("y")
    b = n.get("absoluteBoundingBox") or {}
    return b.get("width"), b.get("height")


def font_of(n):
    st = n.get("style") or {}
    seen = []

    def add(s):
        fam, sty, sz = s.get("fontFamily", st.get("fontFamily")), s.get("fontStyle", st.get("fontStyle")), s.get("fontSize", st.get("fontSize"))
        k = f"{fam}/{sty}/{num(R(sz))}"
        if k not in seen:
            seen.append(k)
    overrides = n.get("characterStyleOverrides") or []
    table = n.get("styleOverrideTable") or {}
    chars = n.get("characters") or ""
    for i in range(len(chars)):
        o = overrides[i] if i < len(overrides) else 0
        add(table.get(str(o), {}) if o else {})
    if not chars:
        add({})
    return "+".join(seen)


def list_segments(n):
    """器の getStyledTextSegments(['listOptions','indentation']) と同じ区間を、行の種類から作る。"""
    chars = n.get("characters") or ""
    types, inds = n.get("lineTypes") or ["NONE"], n.get("lineIndentations") or [0]
    lines, start = [], 0
    for i, ch in enumerate(chars):
        if ch == "\n":
            lines.append((start, i + 1))
            start = i + 1
    lines.append((start, len(chars)))
    segs = []
    for k, (a, b) in enumerate(lines):
        if a == b and k > 0:
            continue
        t = types[k] if k < len(types) else types[-1]
        ind = inds[k] if k < len(inds) else inds[-1]
        if segs and segs[-1]["listOptions"]["type"] == t and segs[-1]["indentation"] == ind:
            segs[-1]["end"] = b
        else:
            segs.append({"start": a, "end": b, "listOptions": {"type": t}, "indentation": ind})
    return segs


def _prop_order(k):
    m = re.search(r"#(\d+):(\d+)$", k)
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def props_of(ctx, n):
    """性質は**名前の順**に並べる。Plugin API が返す順は定義の順でも ID の順でもなく（2026-11-03 実測）、
    REST の順とも合わないので、両方の器で名前の順にそろえる（順に意味は無い）。"""
    out = {}
    items = sorted((n.get("componentProperties") or {}).items(), key=lambda kv: re.sub(r"#[^#]*$", "", kv[0]))
    for k, v in items:
        key = re.sub(r"#[^#]*$", "", k)
        if v.get("type") in ("BOOLEAN", "TEXT"):
            out[key] = v.get("value")
        elif v.get("type") == "INSTANCE_SWAP":
            c = ctx.components.get(v.get("value"))
            out[key] = c["name"] if c else v.get("value")
    return out


def of_name(ctx, n):
    c = ctx.components.get(n.get("componentId"))
    if not c:
        return None, None
    name = c["name"]
    set_id = c.get("componentSetId")
    if set_id and set_id in ctx.component_sets:
        vals = [p.split("=", 1)[1] for p in name.split(", ") if "=" in p]
        return ctx.component_sets[set_id]["name"] + ("/" + ",".join(vals) if vals else ""), c
    return name, c


def ov_value(ctx, node, f):
    if f == "characters":
        return node.get("characters")
    if f == "fills":
        return fills_of(ctx, node)
    if f == "strokes":
        return bn(ctx, node, "strokes") or ("あり" if node.get("strokes") else None)
    if f == "componentProperties":
        return props_of(ctx, node)
    if f in ("textStyleId", "fillStyleId", "strokeStyleId", "effectStyleId"):
        key = {"textStyleId": "text", "fillStyleId": "fill", "strokeStyleId": "stroke", "effectStyleId": "effect"}[f]
        return ctx.style((node.get("styles") or {}).get(key))
    if f in ("fontName", "fontSize"):
        return font_of(node) if node.get("type") == "TEXT" else None
    if f in ("width", "height"):
        w, h = size(node)
        return R(w if f == "width" else h)
    if f == "visible":
        return node.get("visible", True)
    if f == "boundVariables":
        out = {}
        for k, v in bvars(node).items():
            if k == "individualStrokeWeights" and isinstance(v, dict):
                # REST は線ごとの太さの変数を BORDER_*_WEIGHT でまとめて返す。器は strokeTopWeight などの欄で返す
                for side, key in (("BORDER_TOP_WEIGHT", "strokeTopWeight"), ("BORDER_RIGHT_WEIGHT", "strokeRightWeight"),
                                  ("BORDER_BOTTOM_WEIGHT", "strokeBottomWeight"), ("BORDER_LEFT_WEIGHT", "strokeLeftWeight")):
                    if v.get(side):
                        out[key] = ctx.var(v[side], node, key)
                continue
            if node.get("type") == "TEXT" and (node.get("styles") or {}).get("text") and k in TEXT_VAR_KEYS:
                # 器は、文字スタイルの付いた文字の書体の変数を、実際の値（数）と同じときだけ書く。
                # 大きさ・太さは数なので照合できる。行の高さ・書体名は数でないので器はいつも外す（2026-11-03 実測）
                actual = (node.get("style") or {}).get(k) if k in ("fontSize", "fontWeight") else None
                if actual is None or not any(abs(float(actual) - float(x)) <= 1e-6 for x in ctx.values_any_mode(v)):
                    ctx.miss(node, [k], "文字スタイルの実際の値と変数の束縛が不一致、または照合不能")
                    continue
            if k == "rectangleCornerRadii" and isinstance(v, dict):
                # 器の boundVariables は 左上・右上・左下・右下 の順（行の radius= の順とは違う。2026-11-03 実測）
                for c, key in (("RECTANGLE_TOP_LEFT_CORNER_RADIUS", "topLeftRadius"),
                               ("RECTANGLE_TOP_RIGHT_CORNER_RADIUS", "topRightRadius"),
                               ("RECTANGLE_BOTTOM_LEFT_CORNER_RADIUS", "bottomLeftRadius"),
                               ("RECTANGLE_BOTTOM_RIGHT_CORNER_RADIUS", "bottomRightRadius")):
                    if v.get(c):
                        out[key] = ctx.var(v[c], node, key)
                continue
            name = ctx.var(v, node, k)
            if name:
                out[k] = name
        return out
    v = node.get(f, OV_DEFAULT.get(f))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return R(v)
    if isinstance(v, (str, bool)) or v is None:
        return v
    return "あり"


def index_subtree(n, parent=None, out=None, hidden=False):
    out = {} if out is None else out
    h = hidden or n.get("visible", True) is False
    out[n["id"]] = (n, parent, h)
    for c in n.get("children") or []:
        index_subtree(c, n, out, h)
    return out


def overrides_of(ctx, n):
    idx = index_subtree(n)
    ovs = []
    for o in n.get("overrides") or []:
        hit = idx.get(o["id"])
        if not hit or hit[2]:
            # 器は隠れた子を引けない（skipInvisibleInstanceChildren）。同じく ? で残す
            ovs.append(["?", "+".join(o.get("overriddenFields") or [])])
            ctx.miss(n, o.get("overriddenFields") or [], "ノードが引けない（隠れた子への上書きなど。skipInvisibleInstanceChildren）")
            continue
        node = hit[0]
        path, cur = [], hit
        while cur and cur[0]["id"] != n["id"]:
            path.insert(0, cur[0]["name"])
            cur = idx.get(cur[1]["id"]) if cur[1] else None
        fields = list(o.get("overriddenFields") or [])
        # REST は効果のスタイルの上書きを effects としか言わない。器は effectStyleId も挙げる
        if "effects" in fields and (node.get("styles") or {}).get("effect") and "effectStyleId" not in fields:
            fields.append("effectStyleId")
        vals = {}
        for f in sorted(fields, key=lambda s: s.encode("utf-16-be")):   # 器は欄を名前の順（JS の文字の順）で返す
            if f in SKIP_OV:
                continue
            vals[f] = ov_value(ctx, node, f)
        if vals:
            ovs.append(["/".join(path), vals])
    return ovs


def shape(ctx, n, parent):
    p, t = [], n.get("type")
    if True:
        p.append("isMask=" + js(bool(n.get("isMask", False))))
        p.append("layoutPositioning=" + js(n.get("layoutPositioning") or "AUTO"))
        if t != "GROUP" and n.get("constraints"):
            c = n["constraints"]
            p.append("constraints=" + esc(js({"horizontal": CONSTRAINT.get(c.get("horizontal"), c.get("horizontal")),
                                              "vertical": CONSTRAINT.get(c.get("vertical"), c.get("vertical"))})))
        if t in HAS_CLIP:
            p.append("clipsContent=" + js(bool(n.get("clipsContent", False))))
            # REST は数を持たず、子の側に「スクロールしても固定」の印を持つ
            # 器は一番外の画面でだけ数える（中の枠は子に印があっても 0。2026-11-03 実測）
            fixed = sum(1 for c in n.get("children") or [] if c.get("isFixed")) if parent is None else 0
            p.append("numberOfFixedChildren=" + js(n.get("numberOfFixedChildren", fixed)))
        if t not in NO_STROKE:
            p.append("strokeAlign=" + js(n.get("strokeAlign") or "INSIDE"))
            sw = n.get("strokeWeight", 1)
            ind = n.get("individualStrokeWeights") or {}
            if t in HAS_SIDES:
                for side, key in (("top", "strokeTopWeight"), ("right", "strokeRightWeight"),
                                  ("bottom", "strokeBottomWeight"), ("left", "strokeLeftWeight")):
                    p.append(key + "=" + num(ind.get(side, sw)))
            # 辺ごとに違えば、器は strokeWeight を figma.mixed（MIXED）で返す
            p.append("strokeWeight=" + stroke_weight(ctx, n))
    if n.get("visible", True) is False:
        p.append("vis=0")
    if n.get("opacity") is not None and n.get("opacity") != 1:
        p.append("opacity=" + num(R(n["opacity"])))
    fl = fills_of(ctx, n)
    if fl:
        p.append("fill=" + fl)
    fst = ctx.style((n.get("styles") or {}).get("fill"))
    if fst:
        p.append("fillStyle=" + fst)
    # 線の塗り・太さと向き（#184。器と同じ欄）
    if n.get("strokes"):
        p.append("stroke=" + (bn(ctx, n, "strokes") or paint_of(ctx, n, n["strokes"][0])))
        if t != "LINE":
            p.append("outline=" + stroke_weight(ctx, n, True) + ","
                     + (n.get("strokeAlign") or "INSIDE"))
    if t == "LINE":
        p.append("line=" + stroke_weight(ctx, n, True) + ","
                 + (n.get("strokeAlign") or "INSIDE") + "," + str(rotation_deg(n)))
    es = ctx.style((n.get("styles") or {}).get("effect"))
    if es:
        p.append("effect=" + es)
    lm = n.get("layoutMode")
    if lm and lm != "NONE":
        def lv(k):
            # REST は値が既定（0）や、GRID の itemSpacing のように使わない欄を省く。器は値を返すので、
            # **変数に結んでいれば変数の値**を使う（2026-11-03 portfolio の GRID で 20 と 0 に分かれた）
            if k in n:
                return num(n[k])
            bv = (n.get("boundVariables") or {}).get(k)
            v = ctx.value(bv) if bv else None
            if v is None and k == "itemSpacing" and lm == "GRID" and "gridRowGap" in n:
                v = n["gridRowGap"]   # GRID で itemSpacing を返さないとき、器の値は行のすき間と同じ（2026-11-03 実測）
            return num(v) if v is not None else "0"
        p.append("layout=" + ",".join([
            lv("paddingTop"), lv("paddingRight"), lv("paddingBottom"),
            lv("paddingLeft"), lv("itemSpacing"), lm,
            "FIXED" if (n.get("primaryAxisSizingMode") or "AUTO") == "FIXED" else "HUG",
            "FIXED" if (n.get("counterAxisSizingMode") or "AUTO") == "FIXED" else "HUG",
            n.get("primaryAxisAlignItems") or "MIN", n.get("counterAxisAlignItems") or "MIN"]))
    if lm == "GRID":
        p.append("grid=" + ",".join([
            str(n.get("gridRowCount", 0)), str(n.get("gridColumnCount", 0)),
            bn(ctx, n, "gridRowGap") or num(R(n.get("gridRowGap", 0))),
            bn(ctx, n, "gridColumnGap") or num(R(n.get("gridColumnGap", 0))),
            grid_sizes(n.get("gridRowsSizing"), n.get("gridRowCount", 0)),
            grid_sizes(n.get("gridColumnsSizing"), n.get("gridColumnCount", 0))]))
    if parent is not None and parent.get("layoutMode") == "GRID":
        p.append("cell=" + ",".join(str(n.get(k, d)) for k, d in (
            ("gridRowAnchorIndex", 0), ("gridColumnAnchorIndex", 0), ("gridRowSpan", 1), ("gridColumnSpan", 1),
            ("gridChildHorizontalAlign", "AUTO"), ("gridChildVerticalAlign", "AUTO"))))
    binds = []
    for k in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "itemSpacing",
              "counterAxisSpacing", "width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight"):
        v = bn(ctx, n, k)
        if v:
            binds.append(k + ":" + v)
    if binds:
        p.append("bind=" + ",".join(binds))
    raw = ((n.get("sharedPluginData") or {}).get("harness") or {}).get("raw")
    if raw:
        p.append("raw=" + re.sub(r"[|\n]", " ", raw))
    if parent is not None and (parent.get("layoutMode") or "NONE") != "NONE" and n.get("layoutSizingHorizontal"):
        p.append("sz=" + n["layoutSizingHorizontal"] + "," + (n.get("layoutSizingVertical") or "FIXED"))
    radii = n.get("rectangleCornerRadii")
    rbv = (n.get("boundVariables") or {}).get("rectangleCornerRadii") or {}
    if radii and len(set(radii)) > 1:
        p.append("radius=" + ",".join((ctx.var(rbv.get(c), n, "radius") if rbv.get(c) else None) or num(R(v))
                                      for c, v in zip(CORNERS, radii)))
    elif n.get("cornerRadius") or radii:
        cr = n.get("cornerRadius") or radii[0]
        tl = rbv.get(CORNERS[0])
        p.append("radius=" + ((ctx.var(tl, n, "radius") if tl else None) or num(R(cr))))
    elif (n.get("boundVariables") or {}).get("cornerRadius"):
        # 楕円などは REST が cornerRadius の値を返さず、結んだ変数だけを返す。器は値（R(cornerRadius)）を書くので、
        # 変数の値で書く（2026-11-03・414 の Charts/Pie の Ellipse 4 で、器 radius=2・REST は書かず報せが 6 件減った）
        v = ctx.value(n["boundVariables"]["cornerRadius"])
        if v is None:
            ctx.miss(n, ["radius"], "角丸の変数の値が対応表にありません（--variables に値つきの書き出しを渡す）")
        elif v != 0:
            p.append("radius=" + num(R(v)))
    if t == "TEXT":
        p.append("listSegments=" + esc(js(list_segments(n))))
        p.append("text=" + esc(js(n.get("characters") or "")))
        ts = ctx.style((n.get("styles") or {}).get("text"))
        if ts:
            p.append("ts=" + ts)
        fo = font_of(n)
        if fo:
            p.append("font=" + fo)
        p.append("align=" + ((n.get("style") or {}).get("textAlignHorizontal") or "LEFT"))
    if t == "INSTANCE":
        of, comp = of_name(ctx, n)
        if of:
            p.append("of=" + of)
            if comp.get("remote"):
                p.append("remote=1")
            msz = ctx.comp_sizes.get(n.get("componentId"))
            w, h = size(n)
            if msz:
                if R(msz[0]) != R(w) or R(msz[1]) != R(h):
                    p.append(f"override={num(R(msz[0]))}x{num(R(msz[1]))}->{num(R(w))}x{num(R(h))}")
            else:
                ctx.miss(n, ["override"], "部品の定義の寸法を取れない（ライブラリの部品など）")
        else:
            p.append("of=?")
        props = props_of(ctx, n)
        if props:
            p.append("props=" + esc(js(props)))
        ovs = overrides_of(ctx, n)
        if ovs:
            p.append("ov=" + esc(js(ovs)))
    return "|".join(p)


def stroke_weight(ctx, n, rounded=False):
    """器の strokeWeight の値。辺ごとに違えば器は figma.mixed（MIXED）を返す。

    strokeWeight= は器が丸めずに書き、outline=・line= は rn（小数2桁に丸める）で書く
    """
    sw = n.get("strokeWeight", 1)
    ind = n.get("individualStrokeWeights") or {}
    mixed = ind and len({ind.get(s) for s in ("top", "right", "bottom", "left")}) > 1
    return bn(ctx, n, "strokeWeight") or ("MIXED" if mixed else num(R(sw) if rounded else sw))


def rotation_deg(n):
    """器の Math.round(n.rotation)。relativeTransform [[cos, sin, x], [-sin, cos, y]] から角度（度）を出す"""
    rt = n.get("relativeTransform")
    if isinstance(rt, list) and len(rt) == 2:
        deg = math.degrees(math.atan2(rt[0][1], rt[0][0]))
    else:
        deg = math.degrees(n.get("rotation") or 0)
    return int(math.floor(deg + 0.5)) + 0


def _split_top(s, seps=","):
    """区切りで切る（括弧の中は切らない）。seps に空白を入れると空白でも切る"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and (ch in seps or (" " in seps and ch.isspace())):
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def grid_sizes(css, count):
    """REST の gridRowsSizing（CSS の grid-template の書き方）を、器の gridRowSizes の書き方（HUG:1;FLEX:1;FIXED:80）にする。

    REST は `repeat(4,minmax(0,1fr))`・`fit-content(100%)`・`80px` の形で返す（2026-11-03 portfolio で確かめた）。
    読めない形は `?` にして、黙って別の値にしない
    """
    def one(tok):
        tok = tok.strip()
        m = re.fullmatch(r"minmax\(\s*0(?:px)?\s*,\s*([\d.]+)fr\s*\)|([\d.]+)fr", tok)
        if m:
            return "FLEX:" + num(R(float(m.group(1) or m.group(2))))
        if re.fullmatch(r"fit-content\(\s*100%\s*\)|auto|min-content|max-content", tok):
            return "HUG:1"
        m = re.fullmatch(r"([\d.]+)px", tok)
        if m:
            return "FIXED:" + num(R(float(m.group(1))))
        return "?"
    if not css:
        return ";".join(["HUG:1"] * count) if count else ""
    out = []
    # 項目は空白で並ぶ（`minmax(0,1fr) fit-content(100%) …`。2026-11-03 portfolio の 160:5511 で先頭に空白つき）
    for part in _split_top(css, " "):
        m = re.fullmatch(r"repeat\(\s*(\d+)\s*,\s*(.*)\)", part)
        if m:
            out += [one(x) for x in _split_top(m.group(2), " ")] * int(m.group(1))
        else:
            out.append(one(part))
    return ";".join(out)


def rel_xy(n, parent_box):
    """器の x/y（親の中での位置）。REST は geometry=paths のとき relativeTransform を返す。無ければ外接矩形の差"""
    rt = n.get("relativeTransform")
    if isinstance(rt, list) and len(rt) == 2:
        return rt[0][2], rt[1][2]
    b = n.get("absoluteBoundingBox") or {}
    if not parent_box:
        return b.get("x"), b.get("y")
    return b.get("x", 0) - parent_box.get("x", 0), b.get("y", 0) - parent_box.get("y", 0)


def coord_box(parent, grand):
    """子の位置の基準（器と同じく、グループは座標を持たないので、その親の枠を使う）。"""
    return grand if parent and parent.get("type") == "GROUP" else (parent or {}).get("absoluteBoundingBox")


def walk(ctx, n, depth, rows, parent=None, origin=None, in_instance=False, ids=None):
    """ids には rows と同じ順のノード ID を足す（畳んだ行は配列）。器の ids と同じ（2026-11-03・#157）"""
    ids = [] if ids is None else ids
    sh = shape(ctx, n, parent)
    ids.append(n.get("id"))
    w, h = size(n)
    x, y = rel_xy(n, origin)
    rows.append("|".join(str(v) for v in [depth, n["name"], n["type"], num(R(w)), num(R(h)), num(R(x)), num(R(y))])
                + ("|" + sh if sh else ""))
    if depth >= 8:
        if n.get("children"):
            ctx.miss(n, ["children"], "深さの上限8で未取得")
        return
    box = n.get("absoluteBoundingBox") if n.get("type") != "GROUP" else origin
    if n.get("type") == "INSTANCE":
        def find_slots(node, path):
            # 器は部品の中の隠れた子を引かない（skipInvisibleInstanceChildren）。子の一覧からも外れる
            for c in [c for c in node.get("children") or [] if c.get("visible", True) is not False]:
                nxt = path + [c["name"]]
                if c.get("type") == "SLOT":
                    start = len(rows)
                    walk(ctx, c, depth + 1, rows, node, box, True, ids)
                    if len(rows) > start:
                        rows[start] += "|slotPath=" + esc("/".join(nxt))
                elif c.get("type") != "INSTANCE":
                    find_slots(c, nxt)
        find_slots(n, [])
        return
    kids = n.get("children") or []
    if in_instance:
        # 部品の中（差し込み口の中身を含む）では、器は隠れた子を引かない
        kids = [c for c in kids if c.get("visible", True) is not False]
    shapes = [shape(ctx, c, n) for c in kids]
    i = 0
    while i < len(kids):
        j = i
        while (j + 1 < len(kids) and kids[j + 1]["type"] == kids[i]["type"] and shapes[j + 1] == shapes[i]
               and R(size(kids[j + 1])[0]) == R(size(kids[i])[0]) and not kids[i].get("children")):
            j += 1
        if j > i:
            pos = " ".join(f"{num(R(rel_xy(c, box)[0]))},{num(R(rel_xy(c, box)[1]))}" for c in kids[i:j + 1])
            cw, ch = size(kids[i])
            rows.append("|".join(str(v) for v in [depth + 1, kids[i]["name"] + "×" + str(j - i + 1), kids[i]["type"],
                                                  num(R(cw)), num(R(ch)), "-", "-"])
                        + ("|" + shapes[i] if shapes[i] else "") + "|at=" + pos)
            ids.append([c.get("id") for c in kids[i:j + 1]])
        else:
            walk(ctx, kids[i], depth + 1, rows, n, box, in_instance, ids)
        i = j + 1


# ---------------------------------------------------------------------------- 取得

def token():
    t = os.environ.get("FIGMA_TOKEN") or os.environ.get("FIGMA_API_TOKEN")
    if not t:
        raise RuntimeError("FIGMA_TOKEN がありません")
    return t


def get(path, params=None, tok=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"X-Figma-Token": tok or token()})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Figma の応答 {e.code}: {path}") from None


def load_variables(paths):
    names, keys, values, modes = {}, {}, {}, {}

    def walk_v(o):
        if isinstance(o, dict):
            if isinstance(o.get("name"), str) and (o.get("id") or o.get("key")):
                if o.get("id"):
                    names[o["id"]] = o["name"]
                    vals = o.get("values")
                    first = next(iter(vals.values()), None) if isinstance(vals, dict) and vals else None
                    if isinstance(first, (int, float)) and not isinstance(first, bool):
                        values[o["id"]] = first
                    nums = [x for x in (vals or {}).values() if isinstance(x, (int, float)) and not isinstance(x, bool)] \
                        if isinstance(vals, dict) else []
                    if nums:
                        modes[o["id"]] = sorted(set(nums))
                if o.get("key"):
                    keys[o["key"]] = o["name"]
            for v in o.values():
                walk_v(v)
        elif isinstance(o, list):
            for v in o:
                walk_v(v)
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("map"), dict):   # {id: [key, name]} の対応表
            for vid, (k, n) in d["map"].items():
                names[vid], keys[k] = n, n
            values.update(d.get("values") or {})
            modes.update(d.get("modeValues") or {})
        walk_v(d)
    return names, keys, values, modes


def export(file_key, ids, var_paths, parents=None, sections=None, tok=None):
    names, keys, values, modes = load_variables(var_paths)
    if not names and not keys:
        raise RuntimeError("変数の対応表が空です（--variables に id か key を持つ書き出しを渡す）")
    data = get(f"/files/{file_key}/nodes", {"ids": ",".join(ids), "plugin_data": "shared", "geometry": "paths"}, tok)
    styles, components, sets = {}, {}, {}
    for v in data["nodes"].values():
        if v:
            styles.update(v.get("styles") or {})
            components.update(v.get("components") or {})
            sets.update(v.get("componentSets") or {})
    local = [cid for cid, c in components.items() if not c.get("remote")]
    comp_sizes = {}
    for k in range(0, len(local), 50):
        part = get(f"/files/{file_key}/nodes", {"ids": ",".join(local[k:k + 50]), "depth": "1", "geometry": "paths"}, tok)
        for cid, v in part["nodes"].items():
            if v and v.get("document"):
                comp_sizes[cid] = size(v["document"])
    ctx = Ctx(names, keys, styles, components, sets, comp_sizes, values, modes)
    # **変異を直接渡したときは、部品のセットを親として引く**（2026-11-03・414 で見つかった）。
    # 器は親の layoutMode を見て sz= を書く。/nodes は親を返さないので、セットを別に取らないと変異の行だけ sz= が抜ける
    set_of = {fid: (components.get(fid) or {}).get("componentSetId") for fid in ids}
    want = sorted({s for s in set_of.values() if s})
    owners = {}
    for k in range(0, len(want), 50):
        part = get(f"/files/{file_key}/nodes", {"ids": ",".join(want[k:k + 50]), "depth": "1"}, tok)
        for sid, v in part["nodes"].items():
            if v and v.get("document"):
                d = dict(v["document"])
                d.pop("children", None)
                owners[sid] = d
    out = {}
    for fid in ids:
        node = (data["nodes"].get(fid) or {}).get("document")
        if not node:
            raise RuntimeError(f"節点が取れません: {fid}")
        rows, nids = [], []
        walk(ctx, node, 0, rows, owners.get(set_of.get(fid)), (parents or {}).get(fid), ids=nids)
        out[fid] = {**({"section": sections[fid]} if sections and fid in sections else {}), "name": node["name"],
                    "rows": rows, "ids": nids}
    body = js(out)
    return {"frames": out, "$meta": {"読めなかったもの": ctx.not_read, "source": "REST（tools/export_frames_rest.py）"},
            "digest": {"algo": "FNV-1a 32bit", "rows": len(out), "chars": len(body), "value": fnv(body)}}


def pick_frames(file_key, page, sec_names, width, tok=None):
    doc = get(f"/files/{file_key}", {"depth": "3"}, tok)["document"]
    pg = next((p for p in doc["children"] if p["name"] == page), None)
    if not pg:
        raise RuntimeError(f"ページがありません: {page}")
    ids, parents, sections = [], {}, {}
    for sec in pg.get("children") or []:
        if sec.get("type") != "SECTION" or sec["name"] not in sec_names:
            continue
        for fr in sec.get("children") or []:
            w, h = size(fr)
            if fr.get("type") != "FRAME" or round(w or 0) != width or (h or 0) <= 60:
                continue
            ids.append(fr["id"])
            parents[fr["id"]] = sec.get("absoluteBoundingBox")
            sections[fr["id"]] = sec["name"]
    return ids, parents, sections


def locate_parents(file_key, ids, tok=None):
    """ID で指定した画面の、位置の基準（節の中なら節の枠・ページの直下なら無し）と節の名前。"""
    doc = get(f"/files/{file_key}", {"depth": "3"}, tok)["document"]
    parents, sections = {}, {}
    for pg in doc["children"]:
        for sec in pg.get("children") or []:
            if sec.get("id") in ids:
                parents[sec["id"]] = None
            for fr in sec.get("children") or [] if sec.get("type") == "SECTION" else []:
                if fr.get("id") in ids:
                    parents[fr["id"]] = sec.get("absoluteBoundingBox")
                    sections[fr["id"]] = sec["name"]
    return parents, sections


def compare_hashes(manifest_path, rest_path):
    """器が返した行のハッシュ（manifest）と、REST の行を比べる。違う行の番号を返す。"""
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    m = m.get("frames", m)
    r = json.loads(Path(rest_path).read_text(encoding="utf-8"))["frames"]
    out, total = {}, 0
    for fid, info in m.items():
        rows = (r.get(fid) or {}).get("rows")
        if rows is None:
            out[fid] = "REST に無い"
            continue
        hs = info["hashes"]
        total += max(len(hs), len(rows))
        bad = [i for i in range(max(len(hs), len(rows)))
               if i >= len(hs) or i >= len(rows) or hs[i] != fnv(rows[i])]
        if bad:
            out[fid] = bad
        # 器が ID の一覧のハッシュを返していれば、それも照合する（行が同じでも ID が違えば別のノード）
        if "idsHash" in info and info["idsHash"] != fnv(js((r.get(fid) or {}).get("ids"))):
            out[fid + " の ID の一覧"] = "違う"
            total += 1
    return out, total


def compare(a_path, b_path):
    a = json.loads(Path(a_path).read_text(encoding="utf-8"))["frames"]
    b = json.loads(Path(b_path).read_text(encoding="utf-8"))["frames"]
    diffs, total = [], 0
    for fid in sorted(set(a) | set(b)):
        ra, rb = (a.get(fid) or {}).get("rows", []), (b.get(fid) or {}).get("rows", [])
        if fid not in a or fid not in b:
            diffs.append(f"{fid}: 片方にしかありません")
            continue
        for i in range(max(len(ra), len(rb))):
            total += 1
            x, y = (ra[i] if i < len(ra) else None), (rb[i] if i < len(rb) else None)
            if x == y:
                continue
            if x is None or y is None:
                diffs.append(f"{fid} 行{i}: 片方にしかありません: {(x or y)[:80]}")
                continue
            fx, fy = x.split("|"), y.split("|")
            head = "|".join(fx[:3])
            bad = [f"{u} ≠ {v}" for u, v in zip(fx, fy) if u != v][:4]
            if len(fx) != len(fy):
                sx, sy = set(fx), set(fy)
                bad += [f"器だけ: {s[:60]}" for s in sorted(sx - sy)][:3] + [f"REST だけ: {s[:60]}" for s in sorted(sy - sx)][:3]
            diffs.append(f"{fid} 行{i} {head}: " + " / ".join(bad))
        ia, ib = (a.get(fid) or {}).get("ids"), (b.get(fid) or {}).get("ids")
        if ia is not None and ib is not None and ia != ib:
            n = sum(1 for i in range(max(len(ia), len(ib))) if i >= len(ia) or i >= len(ib) or ia[i] != ib[i])
            diffs.append(f"{fid}: ID の一覧が {n} 行で違います")
    return diffs, total


def self_test():
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    ck(R(191.25) == 191.25 and R(36.0) == 36 and R(float("inf")) == "Infinity", "丸めが器と違う")
    ck(num(1.0) == "1" and num(0.5) == "0.5", "数の書き方が JS と違う")
    ck(js({"a": "x|y", "b": True}) == '{"a":"x|y","b":true}', "JSON の書き方が JS と違う")
    ck(esc('a|b') == 'a\\u007cb' and safe("a\u2028b") == "a\\u2028b", "区切りの逃がし方が器と違う")
    ck(hexc({"r": 1, "g": 1, "b": 1, "a": 0.5}) == "#ffffff80" and hexc({"r": 1, "g": 0, "b": 0, "a": 0.5}, alpha=False) == "#ff0000", "色の書き方が器と違う")
    ctx = Ctx({"VariableID:1:1": "Frame/Default"}, {"a" * 40: "Text/Default"}, {"S:1": {"name": "Body/M"}},
              {"C:1": {"name": "Size=M, State=On", "componentSetId": "CS:1"}}, {"CS:1": {"name": "Button"}}, {"C:1": (100, 40)})
    ck(ctx.var({"id": "VariableID:1:1"}) == "Frame/Default", "ローカルの変数を引けない")
    ck(ctx.var({"id": "VariableID:" + "a" * 40 + "/9:9"}) == "Text/Default", "ライブラリの変数を key で引けない")
    node = {"id": "1", "name": "x"}
    ck(ctx.var({"id": "VariableID:9:9"}, node, "fills") == "?" and ctx.not_read, "引けない変数を黙って直値にした")
    inst = {"id": "I", "name": "Btn", "type": "INSTANCE", "componentId": "C:1",
            "absoluteBoundingBox": {"x": 10, "y": 20, "width": 120, "height": 40},
            "children": [{"id": "I;1", "name": "Label", "type": "TEXT", "visible": False, "characters": "A"}],
            "overrides": [{"id": "I", "overriddenFields": ["width", "height"]}, {"id": "I;1", "overriddenFields": ["characters"]}]}
    s = shape(ctx, inst, {"layoutMode": "NONE"})
    ck("of=Button/M,On" in s and "override=100x40->120x40" in s, f"部品の名前・寸法の上書きが器と違う: {s}")
    ck('ov=[["",{"height":40,"width":120}],["?","characters"]]' in s, f"上書きの書き方が器と違う: {s}")
    t = {"id": "T", "name": "T", "type": "TEXT", "characters": "ab\ncd", "lineTypes": ["NONE", "UNORDERED"], "lineIndentations": [0, 1],
         "style": {"fontFamily": "Inter", "fontStyle": "Regular", "fontSize": 12.0, "textAlignHorizontal": "LEFT"},
         "characterStyleOverrides": [0, 0, 0, 1, 1], "styleOverrideTable": {"1": {"fontStyle": "Bold"}}, "styles": {"text": "S:1"}}
    ts = shape(ctx, t, None)
    ck("font=Inter/Regular/12+Inter/Bold/12" in ts and "ts=Body/M" in ts and "UNORDERED" in ts, f"文字の欄が器と違う: {ts}")
    ck(list_segments(t)[0] == {"start": 0, "end": 3, "listOptions": {"type": "NONE"}, "indentation": 0}, "箇条書きの区間が器と違う")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "a.json", Path(td) / "b.json"
        a.write_text(js({"frames": {"1": {"rows": ["0|A|FRAME|1|1|0|0|fill=X"]}}}), encoding="utf-8")
        b.write_text(js({"frames": {"1": {"rows": ["0|A|FRAME|1|1|0|0|fill=Y"]}}}), encoding="utf-8")
        ck(main(["--compare", str(a), str(a)]) == 0, "同じ書き出しを違うと言った")
        hs = Path(td) / "h.json"
        hs.write_text(js({"frames": {"1": {"total": 1, "hashes": [fnv("0|A|FRAME|1|1|0|0|fill=X")]}}}), encoding="utf-8")
        ck(main(["--compare-hashes", str(hs), str(a)]) == 0, "ハッシュが同じなのに違うと言った")
        ck(main(["--compare-hashes", str(hs), str(b)]) == 1, "ハッシュが違うのに同じと言った")
        ai = Path(td) / "ai.json"
        ai.write_text(js({"frames": {"1": {"rows": ["0|A|FRAME|1|1|0|0|fill=X"], "ids": ["1:1"]}}}), encoding="utf-8")
        hi = Path(td) / "hi.json"
        hi.write_text(js({"frames": {"1": {"total": 1, "hashes": [fnv("0|A|FRAME|1|1|0|0|fill=X")],
                                           "idsHash": fnv(js(["9:9"]))}}}), encoding="utf-8")
        ck(main(["--compare-hashes", str(hi), str(ai)]) == 1, "**行が同じでも ID の一覧が違うのに同じと言った**")
        hi.write_text(js({"frames": {"1": {"total": 1, "hashes": [fnv("0|A|FRAME|1|1|0|0|fill=X")],
                                           "idsHash": fnv(js(["1:1"]))}}}), encoding="utf-8")
        ck(main(["--compare-hashes", str(hi), str(ai)]) == 0, "ID の一覧が同じなのに違うと言った")
        bi = Path(td) / "bi.json"
        bi.write_text(js({"frames": {"1": {"rows": ["0|A|FRAME|1|1|0|0|fill=X"], "ids": ["2:2"]}}}), encoding="utf-8")
        ck(main(["--compare", str(ai), str(bi)]) == 1, "**ID の一覧の違いを --compare が見逃した**")
        ck(main(["--compare-hashes", str(hs), str(Path(td) / "none.json")]) == 2, "読めないのに 2 でない")
        ck(main(["--compare", str(a), str(Path(td) / "none.json")]) == 2, "比べる相手が読めないのに 2 でない")
        ck(main(["--compare", str(a), str(b)]) == 1, "違う書き出しを同じと言った")
        old = os.environ.pop("FIGMA_TOKEN", None), os.environ.pop("FIGMA_API_TOKEN", None)
        try:
            ck(main(["--file", "x", "--ids", "1:1", "--variables", str(a), "--out", str(Path(td) / "o.json")]) == 2,
               "鍵が無いのに 2 でない")
        finally:
            if old[0]:
                os.environ["FIGMA_TOKEN"] = old[0]
            if old[1]:
                os.environ["FIGMA_API_TOKEN"] = old[1]
        ck(main(["--file", "x", "--variables", str(a), "--out", str(Path(td) / "o.json")]) == 2, "対象が無いのに 2 でない")

        # ── 書き出しの本体を、網につながずに通す（REST の応答を差し替える）──────────
        # 行の中身の細部は portfolio の実物との照合（--compare-hashes）で見ている。ここでは
        # 「変数・文字・部品・絶対配置・畳み・グループが行になり、壊れずに最後まで回る」ことを見る
        VID = "VariableID:" + "a" * 40 + "/1:2"
        frame = {
            "id": "1:1", "name": "Home", "type": "FRAME", "layoutMode": "VERTICAL",
            "paddingTop": 16, "paddingLeft": 16, "itemSpacing": 8, "clipsContent": True,
            "absoluteBoundingBox": {"x": 100, "y": 0, "width": 390, "height": 800},
            "boundVariables": {"paddingTop": {"type": "VARIABLE_ALIAS", "id": VID}},
            "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 1},
                       "boundVariables": {"color": {"type": "VARIABLE_ALIAS", "id": VID}}}],
            "children": [
                {"id": "1:2", "name": "Title", "type": "TEXT", "characters": "こんにちは",
                 "styles": {"text": "S:1"}, "style": {"fontFamily": "Inter", "fontWeight": 700, "fontSize": 20},
                 "layoutSizingHorizontal": "FILL", "layoutSizingVertical": "HUG",
                 "absoluteBoundingBox": {"x": 116, "y": 16, "width": 358, "height": 24}, "fills": []},
                {"id": "1:3", "name": "Badge", "type": "RECTANGLE", "layoutPositioning": "ABSOLUTE",
                 "rectangleCornerRadii": [4, 4, 0, 0], "relativeTransform": [[1, 0, 360], [0, 1, 0]],
                 "absoluteBoundingBox": {"x": 460, "y": 0, "width": 48, "height": 48}},
                {"id": "1:4", "name": "Dot", "type": "ELLIPSE",
                 "absoluteBoundingBox": {"x": 116, "y": 60, "width": 8, "height": 8}},
                {"id": "1:5", "name": "Dot", "type": "ELLIPSE",
                 "absoluteBoundingBox": {"x": 132, "y": 60, "width": 8, "height": 8}},
                {"id": "1:6", "name": "G", "type": "GROUP",
                 "absoluteBoundingBox": {"x": 116, "y": 80, "width": 20, "height": 20},
                 "children": [{"id": "1:7", "name": "In", "type": "RECTANGLE",
                               "absoluteBoundingBox": {"x": 116, "y": 80, "width": 20, "height": 20}}]},
                {"id": "1:10", "name": "Rule", "type": "LINE", "strokeWeight": 1, "strokeAlign": "CENTER",
                 "strokes": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
                 "relativeTransform": [[0, 1, 116], [-1, 0, 100]],
                 "absoluteBoundingBox": {"x": 116, "y": 100, "width": 1, "height": 20}},
                {"id": "1:11", "name": "Grid", "type": "FRAME", "layoutMode": "GRID", "gridRowCount": 1,
                 "gridColumnCount": 2, "gridRowGap": 4, "gridColumnGap": 8, "gridRowsSizing": "fit-content(100%)",
                 "gridColumnsSizing": "repeat(2,minmax(0,1fr))", "strokes": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}}],
                 "strokeWeight": 2, "strokeAlign": "INSIDE",
                 "absoluteBoundingBox": {"x": 116, "y": 104, "width": 100, "height": 10},
                 "children": [{"id": "1:12", "name": "Cell", "type": "RECTANGLE", "gridColumnAnchorIndex": 1,
                               "absoluteBoundingBox": {"x": 170, "y": 104, "width": 40, "height": 10}}]},
                {"id": "1:8", "name": "Btn", "type": "INSTANCE", "componentId": "C:1",
                 "componentProperties": {"Size": {"type": "VARIANT", "value": "M"}},
                 "absoluteBoundingBox": {"x": 116, "y": 120, "width": 120, "height": 40},
                 "children": [{"id": "I1:8;2:1", "name": "Label", "type": "TEXT", "characters": "送る",
                               "absoluteBoundingBox": {"x": 120, "y": 124, "width": 40, "height": 20}},
                              {"id": "I1:8;2:2", "name": "Hidden", "type": "TEXT", "visible": False,
                               "characters": "x", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1, "height": 1}}]}]}
        page = {"document": {"children": [{"id": "0:1", "name": "Screens", "children": [
            {"id": "9:1", "name": "Main", "type": "SECTION", "absoluteBoundingBox": {"x": 100, "y": 0},
             "children": [frame, {"id": "1:9", "name": "Tiny", "type": "FRAME",
                                  "absoluteBoundingBox": {"x": 0, "y": 0, "width": 390, "height": 40}}]}]}]}}
        nodes = {"nodes": {"1:1": {"document": frame, "styles": {"S:1": {"name": "Heading/L"}},
                                   "components": {"C:1": {"name": "Size=M", "componentSetId": "CS:1"}},
                                   "componentSets": {"CS:1": {"name": "Button"}}},
                           "C:1": {"document": {"id": "C:1", "name": "Size=M", "type": "COMPONENT",
                                                "layoutSizingHorizontal": "FIXED", "layoutSizingVertical": "HUG",
                                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 40}}},
                           "CS:1": {"document": {"id": "CS:1", "name": "Button", "type": "COMPONENT_SET",
                                                 "layoutMode": "HORIZONTAL", "children": [{"id": "C:1"}]}}}}
        calls = []

        def fake_get(path, params=None, tok=None):
            calls.append(path)
            return page if path == "/files/F" else nodes

        vf = Path(td) / "vars.json"
        vf.write_text(js({"map": {VID: ["a" * 40, "Gap/M"]}, "values": {VID: 16}}), encoding="utf-8")
        keep_get, keep_tok = globals()["get"], os.environ.get("FIGMA_TOKEN")
        globals()["get"] = fake_get
        os.environ["FIGMA_TOKEN"] = "x"
        try:
            ids, parents, sections = pick_frames("F", "Screens", ["Main"], 390)
            ck(ids == ["1:1"] and sections == {"1:1": "Main"}, f"節から画面を選べない（低い枠は外す）: {ids}")
            ck(locate_parents("F", ["1:1"])[1] == {"1:1": "Main"}, "ID から節を引けない")
            ck(pick_frames("F", "Screens", ["Other"], 390)[0] == [], "違う節の画面を拾った")
            try:
                pick_frames("F", "None", ["Main"], 390)
                ck(False, "無いページで止まらない")
            except RuntimeError:
                pass
            doc = export("F", ["1:1"], [str(vf)], parents, sections)
            rows = doc["frames"]["1:1"]["rows"]
            whole = "\n".join(rows)
            ck(rows[0].startswith("0|Home|FRAME|390|800|0|0|") and "bind=paddingTop:Gap/M" in rows[0],
               f"画面の行・余白の変数がおかしい: {rows[0]}")
            ck('text="こんにちは"' in whole and "ts=Heading/L" in whole, "文字と文字スタイルが行に無い")
            ck('Badge|RECTANGLE|48|48|360|0|' in whole and 'layoutPositioning="ABSOLUTE"' in whole,
               "絶対配置の印・位置が行に無い（#181）")
            ck("Dot×2|ELLIPSE" in whole and "at=16,60 32,60" in whole, f"同じ形の兄弟を畳めない:\n{whole}")
            ck("|In|RECTANGLE|" in whole, "グループの中の子が行に無い")
            ck("line=1,CENTER,90" in whole and "stroke=SOLID:#000000" in whole, f"線の向き・塗りが行に無い（#184）:\n{whole}")
            # 辺ごとに太さが違うと、strokeWeight= と outline= の両方が MIXED（器は figma.mixed を rn で MIXED にする）
            # 幅・高さの変数（REST は size.x / size.y）を、bind= と上書きの両方で width・height として書く（414）
            sz_n = {"id": "s", "type": "FRAME", "layoutMode": "VERTICAL",
                    "boundVariables": {"size": {"x": {"type": "VARIABLE_ALIAS", "id": VID}},
                                       "paddingTop": {"type": "VARIABLE_ALIAS", "id": VID}}}
            sctx = Ctx({VID: "Gap/M"}, {}, {}, {}, {}, {}, {VID: 16})
            ck("bind=paddingTop:Gap/M,width:Gap/M" in shape(sctx, sz_n, None)
               and list(ov_value(sctx, sz_n, "boundVariables"))[:2] == ["width", "paddingTop"],
               "**幅・高さに結んだ変数（size.x / size.y）を書かない**（414 のアイコンの寸法）")
            el = {"id": "e", "type": "ELLIPSE", "boundVariables": {"cornerRadius": {"type": "VARIABLE_ALIAS", "id": VID}}}
            ck("radius=16" in shape(Ctx({VID: "Gap/M"}, {}, {}, {}, {}, {}, {VID: 16}), el, None),
               "**楕円の角丸（結んだ変数の値）を書かない**（器は値で書く・414）")
            mx = {"id": "m", "type": "FRAME", "strokes": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
                  "strokeWeight": 1, "individualStrokeWeights": {"top": 0, "right": 1, "bottom": 1, "left": 1}}
            sh = shape(Ctx({}, {}, {}, {}, {}, {}), mx, None)
            ck("strokeWeight=MIXED" in sh and "outline=MIXED,INSIDE" in sh, f"辺ごとに違う太さが器と合わない: {sh}")
            ck("grid=1,2,4,8,HUG:1,FLEX:1;FLEX:1" in whole and "outline=2,INSIDE" in whole
               and "cell=0,1,1,1,AUTO,AUTO" in whole, f"グリッド・線の太さ・置き場所が行に無い（#184）:\n{whole}")
            ck("of=Button/M" in whole and "override=100x40->120x40" in whole, "部品と寸法の上書きが行に無い")
            ck("Hidden" not in whole, "部品の中の隠れた子を書いた（器は引かない）")
            # グリッドの大きさの書き方（REST の CSS の形 → 器の HUG:1;FLEX:1;FIXED:80）
            ck(grid_sizes("repeat(4,minmax(0,1fr))", 4) == "FLEX:1;FLEX:1;FLEX:1;FLEX:1"
               and grid_sizes("  minmax(0,1fr) fit-content(100%) 80px", 3) == "FLEX:1;HUG:1;FIXED:80"
               and grid_sizes("repeat(2,fit-content(100%))", 2) == "HUG:1;HUG:1"
               and grid_sizes("subgrid", 1) == "?" and grid_sizes(None, 2) == "HUG:1;HUG:1",
               "グリッドの大きさの書き方を器と同じに直せない")
            ck(rotation_deg({"relativeTransform": [[0, 1, 0], [-1, 0, 0]]}) == 90
               and rotation_deg({"relativeTransform": [[1, 0, 0], [0, 1, 0]]}) == 0, "線の向きを器と同じに出せない")
            nids = doc["frames"]["1:1"]["ids"]
            ck(len(nids) == len(rows) and nids[0] == "1:1" and ["1:4", "1:5"] in nids
               and nids[next(i for i, r in enumerate(rows) if "|Title|" in r)] == "1:2",
               f"ID の一覧が行と並ばない（畳んだ行は配列）: {nids}")
            ck(doc["digest"]["value"] == fnv(js(doc["frames"])), "ハッシュが本体と合わない")
            # 変異を直接渡すと、部品のセットを親として sz= を書く（器と同じ。2026-11-03・414）
            v = export("F", ["C:1"], [str(vf)])["frames"]["C:1"]["rows"][0]
            ck("|sz=FIXED,HUG" in v, f"**変異の行に sz= が無い**（セットを親として引いていない）: {v}")
            out = Path(td) / "rest.json"
            ck(main(["--file", "F", "--ids", "1:1", "--variables", str(vf), "--out", str(out)]) == 0
               and json.loads(out.read_text(encoding="utf-8"))["frames"]["1:1"]["rows"] == rows,
               "--ids で書き出せない・行が違う")
            ck(main(["--file", "F", "--page", "Screens", "--section", "Main", "--width", "390",
                     "--variables", str(vf), "--out", str(out)]) == 0, "--page/--section/--width で書き出せない")
            ck(main(["--file", "F", "--page", "Screens", "--section", "Other", "--width", "390",
                     "--variables", str(vf), "--out", str(out)]) == 2, "対象 0 件なのに 2 でない")
            empty = Path(td) / "empty.json"
            empty.write_text("{}", encoding="utf-8")
            ck(main(["--file", "F", "--ids", "1:1", "--variables", str(empty), "--out", str(out)]) == 2,
               "変数の対応表が空なのに 2 でない")
            ck(main(["--file", "F", "--ids", "1:404", "--variables", str(vf), "--out", str(out)]) == 2,
               "取れない節点で 2 でない")
        finally:
            globals()["get"] = keep_get
            if keep_tok is None:
                os.environ.pop("FIGMA_TOKEN", None)
            else:
                os.environ["FIGMA_TOKEN"] = keep_tok
    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="画面の書き出しを Figma の REST API から作る（器と同じ行の形）")
    ap.add_argument("--file")
    ap.add_argument("--ids", help="画面のノード ID（カンマ区切り）")
    ap.add_argument("--page")
    ap.add_argument("--section", action="append", default=[])
    ap.add_argument("--width", type=int)
    ap.add_argument("--variables", action="append", default=[], help="Variables の書き出し（id か key を持つ）")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--compare", nargs=2, metavar=("器の書き出し", "RESTの書き出し"))
    ap.add_argument("--compare-hashes", nargs=2, metavar=("器の行のハッシュ", "RESTの書き出し"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.compare_hashes:
        try:
            bad, total = compare_hashes(*a.compare_hashes)
        except (OSError, KeyError, json.JSONDecodeError) as e:
            print(f"比べられません: {e}", file=sys.stderr)
            return 2
        if bad:
            n = sum(len(v) if isinstance(v, list) else 1 for v in bad.values())
            print(f"**{n} 行が違います**（{total} 行中）: " + js(bad), file=sys.stderr)
            return 1
        print(f"{total} 行すべて一致しました（ハッシュ）")
        return 0
    if a.compare:
        try:
            diffs, total = compare(*a.compare)
        except (OSError, KeyError, json.JSONDecodeError) as e:
            print(f"比べられません: {e}", file=sys.stderr)
            return 2
        if diffs:
            print(f"**{len(diffs)} 行が違います**（{total} 行中）:", file=sys.stderr)
            for d in diffs[:60]:
                print("  " + d, file=sys.stderr)
            return 1
        print(f"{total} 行すべて一致しました")
        return 0
    try:
        if a.ids:
            ids = [x.strip() for x in a.ids.split(",") if x.strip()]
            parents, sections = locate_parents(a.file, ids) if a.file else (None, None)
        elif a.page and a.section and a.width:
            ids, parents, sections = pick_frames(a.file, a.page, a.section, a.width)
        else:
            ids = []
        if not a.file or not ids or not a.out:
            print("--file・対象（--ids か --page/--section/--width）・--out が要ります。対象が 0 件です", file=sys.stderr)
            return 2
        doc = export(a.file, ids, a.variables, parents, sections)
    except (RuntimeError, OSError, json.JSONDecodeError) as e:
        print(f"書き出せませんでした: {e}", file=sys.stderr)
        return 2
    a.out.write_text(safe(js(doc)), encoding="utf-8")
    print(f"{len(doc['frames'])} 画面・{sum(len(f['rows']) for f in doc['frames'].values())} 行を書きました: {a.out}"
          f"（読めなかったもの {len(doc['$meta']['読めなかったもの'])} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
