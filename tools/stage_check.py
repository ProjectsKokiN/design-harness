#!/usr/bin/env python3
"""verify.sh の各段が「落ちるところを見た」道具かを見る（aub 提案10・2026-08-29）。

## 実害

> 何も見ていない検査が緑で並ぶ。**この日だけで2回踏んだ**（aub-familywalk）

「落ちることを見てから採用する」は文章の決まりとして書いてあったが、
文章では守れなかった。**手順ではなく検査にする。**

## 2つのモード

| | 見るもの |
|---|---|
| 既定 | 並んでいる段の**質**（その道具は落ちるところを見たか） |
| `--stages` | 並んでいる段の**数**（元ファイルにある段が、この案件から落ちていないか） |

`--stages` の実害（flash-compose・2026-09-02〜03）:

- `ci/verify.sh.template` に「ページの範囲」の段があるのに、案件の `verify.sh` から
  **その1行が落ちていた**。2026-08-29 に規則を決めてから 09-02 まで、
  3段構えのうち検査の段が**一度も走っていなかった**
- 関門の**条件5と条件7 を誰も測っていなかった**。条件7 は「飛ばしました。
  条件7 が誰も見ていません」と自分で言いながら CI は緑、条件5 は段そのものが無く、
  飛ばした記録すら残らない
- 元ファイルの18段のうち **7段がどこにも無かった**（`verify.sh`・CI・案件シムの
  いずれにも）。**数件は正しく不在**（設定がレジストリ側にあり、レジストリの CI が
  走らせている）だが、残りはそうではなかった

**問題は「段が無いこと」ではなく、「無い理由を宣言する場所が無いこと」。**
意図して当てはまらない段と、黙って落ちた段が区別できない。どちらも
「その行が無い」だけの見た目になる。だから**理由つきで宣言させる**
（`impl-coverage.json` の未実装宣言・`figma_layout_test` の notChecked と同じ形）。

分母は3つとも**導出する。手で書かない**:

    production-gate.md（正本）→ gate/conditions.json（生成物）→ 元ファイルの段の札
                                                              → 案件が走らせている段

## 見るもの（既定のモード）

`verify.sh` の `step "..." ...` の各行について:

1. design-harness の道具を呼んでいるなら、その道具に `--self-test` があるか
2. あるなら、**実際に走らせて通るか**
3. 無いなら、`README.md` の例外表に理由つきで載っているか

## 捕まえないもの

- 案件固有のコマンド（`flutter test` / `npx tsc` など）。外部の道具なので
  self-test の有無を問わない。**ただし一覧には出す**（何が無検査かを見えるように）
- **落ちるケースが本物か**（`--min-coverage` は行数しか見ない。1行通れば
  数には入る）。中身が正しいかは人が見る
- 確かめた方法: --self-test（self-test の無い道具を段に足すと落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/stage_check.py [--verify design/verify.sh]
    python3 design/harness/tools/stage_check.py --stages    # 段の数を見る
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HERE = Path(__file__).resolve().parent
STEP_RX = re.compile(r'^\s*step\s+"([^"]+)"\s+(.*)$')
TOOL_RX = re.compile(r'(?:\$HARNESS|harness)/tools/([a-z_]+)\.py')
#: 段が走らせるファイルの名前（パスは落とす）。案件シム経由でも同じ名前になる
FILE_RX = re.compile(r"(?:^|[\s/\"'])([a-z_][a-z0-9_]*\.(?:py|sh))\b")
#: README の例外表から拾う道具名
EXC_RX = re.compile(r"^\|\s*`?([a-z_]+)`?[^|]*\|")


def logical_lines(text):
    """行継続（末尾の `\\`）をつないで1行にする。

    **2026-08-29 に自分で踏んだ**: verify.sh.template は
    `step "..." \\` で改行しており、継続を読まないと道具のパスが次の行に残る。
    その結果この道具は**全部の段を「外部の道具」と分類して緑を返した**——
    まさにこの道具が捕まえるはずの「何も見ていない検査」そのものだった。
    """
    out, buf = [], ""
    for line in text.splitlines():
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        out.append(buf + line)
        buf = ""
    if buf:
        out.append(buf)
    return out


def documented_exceptions(readme):
    """README の「self-test を持たない道具」表に載っている道具名。"""
    if not readme.exists():
        return set()
    text = readme.read_text(encoding="utf-8")
    m = re.search(r"##\s*self-test を持たない道具.*?(?=\n##\s|\Z)", text, re.S)
    if not m:
        return set()
    out = set()
    for line in m.group(0).splitlines():
        mm = EXC_RX.match(line)
        if mm and mm.group(1) not in ("道具", "理由"):
            for name in re.findall(r"`([a-z_]+)`", line):
                out.add(name)
    return out


def self_test_stages():
    """--stages の妨害テスト（#4・#12）。

    **段が1つ落ちたら落ちること**が本体。落ちなければ、この道具は
    「黙って落ちた段」と「意図して当てはまらない段」を区別できていない。
    """
    import contextlib
    import io
    import tempfile
    ok = True
    TPL = (
        'step "禁止パターン（全量・条件1）" "$PY" design/design_check.py --all\n'
        'step "実装網羅（条件7: 全部実装）" \\\n'
        '  "$PY" "$HARNESS/tools/impl_coverage_check.py" --config impl-coverage.json\n'
        'step "再現性の判定（条件5: 描画で別物）" \\\n'
        '  "$PY" "$HARNESS/tools/check_render_gaps.py" --config c.json\n'
        'step "種まき（条件8: 発火するか）" "$PY" "$HARNESS/tools/seed_check.py"\n'
        'step "移植性（Windows でだけ落ちる書き方）" \\\n'
        '  "$PY" "$HARNESS/tools/portable_check.py" --style\n'
    )
    GATE = {"生きている条件": {c: {"見出し": f"じょうけん{c}"}
                              for c in ("1", "5", "7", "8")}}

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design").mkdir()
        tpl = root / "template.sh"
        gate = root / "conditions.json"
        verify = root / "design" / "verify.sh"
        waivers = root / "design" / "stages.json"
        tpl.write_text(TPL, encoding="utf-8")
        gate.write_text(json.dumps(GATE, ensure_ascii=False), encoding="utf-8")

        full = ('python3 design/design_check.py --all\n'
                'python3 $HARNESS/tools/impl_coverage_check.py --config x\n'
                'python3 $HARNESS/tools/check_render_gaps.py --config c.json\n'
                'python3 $HARNESS/tools/seed_check.py\n'
                'python3 $HARNESS/tools/portable_check.py --style\n')

        def run(sh, waiver=None, tpl_text=None, gate_data=None):
            verify.write_text(sh, encoding="utf-8")
            tpl.write_text(tpl_text or TPL, encoding="utf-8")
            gate.write_text(json.dumps(gate_data or GATE, ensure_ascii=False),
                            encoding="utf-8")
            waivers.unlink(missing_ok=True)
            if waiver is not None:
                waivers.write_text(json.dumps({"notHere": waiver},
                                              ensure_ascii=False), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = check_stages(tpl, verify, None, waivers, gate)
            return rc, buf.getvalue()

        def case(name, want, needle=None, **kw):
            nonlocal ok
            rc, out = run(**kw)
            if rc != want:
                print(f"self-test NG: {name} → exit {rc}（期待 {want}）")
                print("   " + out.strip().replace("\n", "\n   ")[:400])
                ok = False
            elif needle and needle not in out:
                print(f"self-test NG: {name} → 「{needle}」が出ていない")
                ok = False

        case("段が全部あれば通る", 0, sh=full)
        case("段が1つ落ちたら落ちる", 1, "黙って落ちた段と区別が付きません",
             sh=full.replace("python3 $HARNESS/tools/portable_check.py --style\n", ""))
        case("理由つきの宣言があれば通る", 0,
             sh=full.replace("python3 $HARNESS/tools/portable_check.py --style\n", ""),
             waiver={"移植性（Windows でだけ落ちる書き方）":
                     {"why": "Mac だけで開発している", "reviewBy": "2099-01-01"}})
        case("理由の無い宣言は通さない", 1, "why",
             sh=full.replace("python3 $HARNESS/tools/portable_check.py --style\n", ""),
             waiver={"移植性（Windows でだけ落ちる書き方）": {"reviewBy": "2099-01-01"}})
        case("棚卸しの期限が切れた宣言は通さない", 1, "期限",
             sh=full.replace("python3 $HARNESS/tools/portable_check.py --style\n", ""),
             waiver={"移植性（Windows でだけ落ちる書き方）":
                     {"why": "x", "reviewBy": "2020-01-01"}})
        case("走っている段の宣言が残っていたら落とす（宣言が古い）", 1,
             "宣言のほうが古くなっています", sh=full,
             waiver={"移植性（Windows でだけ落ちる書き方）":
                     {"why": "x", "reviewBy": "2099-01-01"}})

        # 関門の条件を持つ段は、理由だけでは足りない。**どこで測っているか**
        gone = full.replace(
            "python3 $HARNESS/tools/check_render_gaps.py --config c.json\n", "")
        case("関門の段の宣言に measuredBy が無ければ落とす", 1, "measuredBy",
             sh=gone, waiver={"再現性の判定（条件5: 描画で別物）":
                              {"why": "設定がレジストリ側", "reviewBy": "2099-01-01"}})
        case("どこで測っているかを書けば通る", 0, sh=gone,
             waiver={"再現性の判定（条件5: 描画で別物）":
                     {"why": "設定がレジストリ側", "reviewBy": "2099-01-01",
                      "measuredBy": "design-systems の CI が走らせている"}})

        # 元ファイル自身の穴・廃止した条件・案件で測られていない条件
        case("生きている条件を元ファイルのどの段も測らないなら落とす", 1,
             "元ファイルのどの段も測ると言っていません", sh=full,
             gate_data={"生きている条件": {**GATE["生きている条件"],
                                          "9": {"見出し": "見本と相互作用"}}})
        case("廃止した条件を名乗る段があれば落とす", 1, "廃止済み", sh=full,
             tpl_text=TPL + 'step "照合体制（条件2: 廃止済み）" '
                            '"$PY" "$HARNESS/tools/coverage_check.py"\n')
        case("参考と書いてあれば札とみなさない", 0, sh=full + "coverage_check.py\n",
             tpl_text=TPL + 'step "照合体制（参考: 条件2 は廃止）" '
                            '"$PY" "$HARNESS/tools/coverage_check.py"\n')

        # 関門の条件の一覧そのものが無ければ落とす
        gate.unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = check_stages(tpl, verify, None, waivers, gate)
        if rc != 2 or "確かめる手段がない" not in buf.getvalue():
            print(f"self-test NG: 条件の一覧が無いのに通した（exit {rc}）"); ok = False
    return ok


def self_test_coverage(tool_path):
    """その道具の self-test が、本体を何行通るかを返す（2026-09-02 新設）。

    **`stage_check` はそれまで「self-test を持っているか」しか見ていなかった。**
    持っていても中身が薄ければ、何も見ていないのと同じ。実測で分かった例:

      fingerprint_parity   80行中  9行（11%）… 固定具の識別力だけを見ており、
                                              **main() を1行も通っていなかった**
      impl_coverage_check  36行中  7行（19%）… トークン照合の本体が0行
                                              （planttalk が 2026-09-02 に指摘）

    実行行は `ast` で数える（コメントと文字列だけの行を除くため）。
    戻りは (本体の行数, 通った行数) または None（self-test を持たない）。
    """
    import ast as _ast
    import importlib.util as _ilu
    import io as _io
    import contextlib as _ctx

    src = tool_path.read_text(encoding="utf-8")
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    st = next((n for n in _ast.walk(tree)
               if isinstance(n, _ast.FunctionDef) and n.name == "self_test"), None)
    if st is None:
        return None
    st_lines = set(range(st.lineno, (st.end_lineno or st.lineno) + 1))
    body = {n.lineno for n in _ast.walk(tree)
            if isinstance(n, _ast.stmt) and n.lineno not in st_lines}
    if not body:
        return None

    spec = _ilu.spec_from_file_location(f"_cov_{tool_path.stem}", tool_path)
    mod = _ilu.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None

    hit = set()
    name = tool_path.name

    def tr(frame, ev, arg):
        if ev == "line" and frame.f_code.co_filename.endswith(name):
            hit.add(frame.f_lineno)
        return tr

    # **入れ子で呼ばれる**（この道具自身の self-test が main() を通ってここへ来る）。
    # 内側が `settrace(None)` で終わると**外側の計測がそこで止まる**ので、
    # 前の追跡係を保存して戻す。2026-09-04 の実測: この1行が無いために
    # stage_check の網羅が 53%（実は 27% までしか測れていない）と出ていた。
    # **計測そのものが嘘をついていた形**で、この段が捕まえるはずのものだった。
    prev = sys.gettrace()
    sys.settrace(tr)
    try:
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            mod.self_test()
    except SystemExit:
        pass
    except Exception:
        pass
    finally:
        sys.settrace(prev)
    return len(body), len(body & hit)


# ─── 段の数（--stages）────────────────────────────────────────────────
#: 段の見出しに付いた関門の札。`step "実装網羅（条件7: …）"` の 7 を拾う
COND_RX = re.compile(r"条件(\d+)")
#: 廃止した条件を名乗っている段。`（参考: 条件2 は … 廃止）` は札ではない
COND_SKIP = "参考"

WAIVER_KEYS = ("why", "reviewBy")


def template_stages(path):
    """元ファイルに並んでいる段を「見出し → 走らせるファイル名の集合」で返す。

    **道具名ではなくファイル名で持つ。** 案件は `$HARNESS/tools/design_check.py`
    ではなく案件シム（`design/design_check.py`）を呼ぶことがあり、道具名で
    照合すると**シム経由の段を「無い」と誤判定する**（2026-09-04 に self-test で
    発覚。この道具が捕まえるはずの偽の赤だった）。

    コメントアウトされた段（`# step "静的解析" {{…}}`）は数えない。
    案件が具体化するひな形であって、走る段ではない。
    """
    out = {}
    for line in logical_lines(path.read_text(encoding="utf-8")):
        m = STEP_RX.match(line)
        if not m:
            continue
        out[m.group(1)] = set(FILE_RX.findall(m.group(2)))
    return out


def project_tools(verify_path, ci_dir):
    """この案件が実際に走らせているファイル名を集める。

    `verify.sh` だけでなく **CI の YAML も見る**。段は片方にしか無いことがある
    （鮮度は担当機だけ、実装網羅は CI だけ、など）。
    """
    seen, where = set(), {}

    def eat(text, src):
        for name in FILE_RX.findall(text):
            seen.add(name)
            where.setdefault(name, src)

    if verify_path.exists():
        eat(verify_path.read_text(encoding="utf-8"), verify_path.name)
    if ci_dir and ci_dir.exists():
        for y in sorted(ci_dir.glob("*.yml")) + sorted(ci_dir.glob("*.yaml")):
            eat(y.read_text(encoding="utf-8", errors="ignore"), y.name)
    return seen, where


def _conditions_of(label):
    """段の見出しから関門の条件番号を拾う。「参考:」と書いてあれば札ではない。"""
    if COND_SKIP in label:
        return set()
    return set(COND_RX.findall(label))


def check_stages(template, verify, ci_dir, waivers_path, gate_path):
    """元ファイルの段が、この案件から黙って落ちていないかを見る。"""
    if not template.exists():
        print(f"元ファイルがありません: {template}", file=sys.stderr)
        return 2
    stages = template_stages(template)
    if not stages:
        print(f"元ファイルから段を読めませんでした: {template}", file=sys.stderr)
        return 2
    have, where = project_tools(verify, ci_dir)

    live = {}
    if gate_path and gate_path.exists():
        try:
            live = json.loads(gate_path.read_text(
                encoding="utf-8")).get("生きている条件", {})
        except (OSError, json.JSONDecodeError) as e:
            print(f"関門の条件が読めません: {gate_path}: {e}", file=sys.stderr)
            return 2
    else:
        print(f"関門の条件がありません: {gate_path}\n"
              f"  `python3 tools/gen_gate.py` で生成してください。"
              f"**条件が何件かを確かめる手段がない状態です。**", file=sys.stderr)
        return 2

    waivers = {}
    if waivers_path and waivers_path.exists():
        try:
            waivers = json.loads(waivers_path.read_text(
                encoding="utf-8")).get("notHere", {})
        except (OSError, json.JSONDecodeError) as e:
            print(f"段の宣言が読めません: {waivers_path}: {e}", file=sys.stderr)
            return 2

    errs, waived, ran = [], [], []
    covered = set()          # この案件で実際に測っている関門の条件
    claimed = set()          # 元ファイルが測ると言っている条件

    for label, tools in stages.items():
        conds = _conditions_of(label)
        claimed |= conds
        if not tools:
            # 走らせるファイルが読めない段（案件固有のコマンド）。
            # **分母から外す**（`flutter test` などは案件ごとに形が違う）
            continue
        if tools & have:
            ran.append(label)
            covered |= conds
            if label in waivers:
                errs.append(f"  「{label}」は走っているのに、"
                            f"{waivers_path.name} で不在と宣言されています。\n"
                            f"    宣言のほうが古くなっています。消してください。")
            continue

        w = waivers.get(label)
        if not isinstance(w, dict):
            errs.append(f"  「{label}」が この案件にありません（宣言もありません）。\n"
                        f"    元ファイル: {template}\n"
                        f"    当てはまらないなら {waivers_path.name} に理由を"
                        f"書いてください。**黙って落ちた段と区別が付きません。**")
            continue
        missing = [k for k in WAIVER_KEYS if not str(w.get(k, "")).strip()]
        if missing:
            errs.append(f"  「{label}」の宣言に {' / '.join(missing)} が"
                        f"ありません（理由と棚卸しの期限は必須）。")
            continue
        if str(w["reviewBy"]) < date.today().isoformat():
            errs.append(f"  「{label}」の宣言は棚卸しの期限"
                        f"（{w['reviewBy']}）を過ぎています。\n"
                        f"    **理由がまだ生きているか確かめてください。**")
            continue
        if conds:
            # 関門の条件を持つ段は、理由だけでは足りない。
            # **どこで測っているか**を書かせる（条件は全部満たす、が正本の決まり）
            if not str(w.get("measuredBy", "")).strip():
                errs.append(f"  「{label}」は関門の"
                            f"{' / '.join('条件' + c for c in sorted(conds))}"
                            f"を測る段です。\n"
                            f"    不在にするなら measuredBy に**どこで測っているか**"
                            f"を書いてください\n"
                            f"    （例: 「design-systems の CI が走らせている」）。"
                            f"理由だけでは足りません。")
                continue
            covered |= conds
        waived.append(label)

    # 元ファイル自身の穴: 生きている条件なのに、どの段も測ると言っていない
    for c in sorted(live):
        if c not in claimed:
            errs.append(f"  関門の条件{c}（{live[c].get('見出し')}）を、"
                        f"元ファイルのどの段も測ると言っていません。\n"
                        f"    {template} の段の見出しに「条件{c}」の札が要ります。")

    # 廃止した条件を名乗っている段
    for c in sorted(claimed - set(live)):
        errs.append(f"  段が条件{c} を名乗っていますが、正本にその条件は"
                    f"ありません（廃止済み）。\n"
                    f"    札を「参考」に付け替えてください。")

    # この案件で、生きている条件が全部測られているか
    for c in sorted(set(live) & claimed):
        if c not in covered:
            errs.append(f"  関門の条件{c}（{live[c].get('見出し')}）を、"
                        f"この案件では誰も測っていません。\n"
                        f"    **「条件は全部満たす」が正本の決まりです。**")

    if errs:
        print("元ファイルの段が、この案件から落ちています:", file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    note = f" / 理由つきで不在 {len(waived)}段" if waived else ""
    print(f"段の数: 元ファイル {len(stages)}段 → この案件 {len(ran)}段{note}。"
          f"関門の条件 {len(live)} 件、すべて測っています。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify.sh の段が検査済みの道具か")
    ap.add_argument("--verify", type=Path, default=Path("design/verify.sh"))
    ap.add_argument("--tools", type=Path, default=HERE)
    ap.add_argument("--readme", type=Path, default=HERE.parent / "README.md")
    ap.add_argument("--run", action="store_true", default=True,
                    help="self-test を実際に走らせる（既定）")
    ap.add_argument("--no-run", dest="run", action="store_false")
    ap.add_argument("--min-coverage", type=int, metavar="N",
                    help="self-test が道具の本体の N%% 以上を通ることを求める。"
                         "省くと測って表示するだけ")
    ap.add_argument("--stages", action="store_true",
                    help="元ファイルの段が、この案件から落ちていないかを見る")
    ap.add_argument("--template", type=Path,
                    default=HERE.parent / "ci" / "verify.sh.template")
    ap.add_argument("--ci", type=Path, default=Path(".github/workflows"))
    ap.add_argument("--waivers", type=Path, default=Path("design/stages.json"))
    ap.add_argument("--gate", type=Path, default=HERE.parent / "gate" / "conditions.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.stages:
        return check_stages(args.template, args.verify, args.ci,
                            args.waivers, args.gate)

    if not args.verify.exists():
        print(f"verify.sh がありません: {args.verify}\n"
              f"  統合検査の入口が無い状態です（関門は CI と pre-push）。",
              file=sys.stderr)
        return 1

    exceptions = documented_exceptions(args.readme)
    problems, foreign, checked = [], [], []

    lines = logical_lines(args.verify.read_text(encoding="utf-8"))
    seen_step = False
    for line in lines:
        m = STEP_RX.match(line)
        if m:
            seen_step = True
            label, cmd = m.group(1), m.group(2)
        else:
            # `step "..."` の形でない verify.sh もある（案件が手で書いた場合）。
            # **形式に依らず道具の呼び出しを拾う**（2026-08-29。それまで step 行
            # だけを見ており、形式の違う3案件を「0段・OK」と報告していた——
            # まさにこの道具が捕まえるはずの偽の緑だった）
            if not TOOL_RX.search(line):
                continue
            label, cmd = line.strip()[:60], line
        tools = TOOL_RX.findall(cmd)
        if not tools:
            foreign.append(label)
            continue
        for name in tools:
            path = args.tools / f"{name}.py"
            if not path.exists():
                problems.append(f"「{label}」が呼ぶ {name}.py がありません")
                continue
            src = path.read_text(encoding="utf-8", errors="ignore")
            if "self_test" not in src:
                if name in exceptions:
                    foreign.append(f"{label}（{name}: 例外として明記済み）")
                else:
                    problems.append(
                        f"「{label}」が呼ぶ {name}.py に self-test がありません。\n"
                        f"      **落ちるところを見ていない検査を段に置かない。**\n"
                        f"      落ちるケースを足すか、README の例外表に理由を書いてください")
                continue
            if not args.run:
                checked.append(name)
                continue
            r = subprocess.run([sys.executable, str(path), "--self-test"],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                problems.append(f"「{label}」の {name}.py の self-test が落ちました:\n"
                                f"      {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[:150]}")
            else:
                checked.append(name)

    # 空振り検知: 中身があるのに1つも拾えていないなら、読み方が合っていない
    meaningful = [l for l in lines
                  if l.strip() and not l.strip().startswith("#")]
    if not checked and not foreign and len(meaningful) > 5:
        print(f"デザインハーネス異常: {args.verify} に {len(meaningful)} 行あるのに、"
              f"検査の段を1つも拾えませんでした。\n"
              f"  **『0段・問題なし』は『何も見ていない』という意味です。**\n"
              f"  ハーネスの道具を design/harness/tools/ 経由で呼ぶか、"
              f"雛形（ci/verify.sh.template）の step 形式に寄せてください。",
              file=sys.stderr)
        return 2

    print(f"段の健全性: 道具の段 {len(checked)}件が self-test 済み / "
          f"外部・例外の段 {len(foreign)}件")
    for f in foreign:
        print(f"  自己検査なし（外部の道具）: {f}")

    # **self-test の中身の薄さを測る**（2026-09-02 新設）。
    # それまで「持っているか」しか見ておらず、持っていても本体を1行も
    # 通らない道具があった（fingerprint_parity 11%・impl_coverage_check の
    # トークン照合は 0行）
    rows = []
    for tp in sorted(args.tools.glob("*.py")):
        r = self_test_coverage(tp)
        if r is None:
            continue
        body, hit = r
        rows.append((tp.stem, body, hit, hit * 100 // max(body, 1)))
    if rows:
        rows.sort(key=lambda x: x[3])
        thin = [r for r in rows if args.min_coverage and r[3] < args.min_coverage]
        print(f"\nself-test の網羅（道具 {len(rows)}本）: "
              f"最小 {rows[0][3]}% / 中央 {sorted(r[3] for r in rows)[len(rows)//2]}% / "
              f"最大 {rows[-1][3]}%")
        for name, body, hit, pct in rows[:5]:
            mark = "  ← **薄い**" if args.min_coverage and pct < args.min_coverage else ""
            print(f"  {name:<26} {hit:>3}/{body:<3}行 {pct:>3}%{mark}")
        if thin:
            problems.append(
                f"self-test が本体の {args.min_coverage}% を通らない道具が"
                f" {len(thin)} 本あります: "
                + " / ".join(f"{n}({p}%)" for n, _, _, p in thin)
                + "\n    **持っているだけでは何も証明していません。**"
                  "落ちるケースを足してください")

    if problems:
        print("\n落ちるところを見ていない段があります:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        tools = base / "tools"; tools.mkdir()
        (tools / "good.py").write_text(
            "import sys\ndef self_test():\n    print('self-test: OK')\n    return 0\n"
            "if __name__ == '__main__':\n    sys.exit(self_test())\n", encoding="utf-8")
        (tools / "bad.py").write_text("print('検査したふり')\n", encoding="utf-8")
        (tools / "failing.py").write_text(
            "import sys\ndef self_test():\n    return 1\n"
            "if __name__ == '__main__':\n    sys.exit(self_test())\n", encoding="utf-8")
        readme = base / "README.md"
        readme.write_text("## self-test を持たない道具（意図的な例外）\n\n"
                          "| 道具 | 理由 |\n|---|---|\n| `bad` | 外部に依存する |\n",
                          encoding="utf-8")
        v = base / "verify.sh"

        def run(body):
            v.write_text(body, encoding="utf-8")
            return main(["--verify", str(v), "--tools", str(tools),
                         "--readme", str(readme)])

        if run('step "よい段" "$PY" "$HARNESS/tools/good.py"\n') != 0:
            print("self-test NG: self-test のある道具で落ちた"); ok = False
        if run('step "落ちる段" "$PY" "$HARNESS/tools/failing.py"\n') != 1:
            print("self-test NG: self-test が落ちる道具を通した"); ok = False
        if run('step "例外の段" "$PY" "$HARNESS/tools/bad.py"\n') != 0:
            print("self-test NG: README に明記した例外で落ちた"); ok = False
        readme.write_text("（例外表なし）\n", encoding="utf-8")
        if run('step "無検査の段" "$PY" "$HARNESS/tools/bad.py"\n') != 1:
            print("self-test NG: self-test の無い道具を黙って通した"); ok = False
        if run('step "外部の段" flutter test\n') != 0:
            print("self-test NG: 外部コマンドの段で落ちた"); ok = False

        # step 形式でない verify.sh でも道具を拾えること
        readme.write_text("（例外表なし）\n", encoding="utf-8")
        if run('#!/bin/sh\nset -e\n'
               'echo "検査します"\n'
               'python3 design/harness/tools/bad.py\n'
               'echo "おわり"\n') != 1:
            print("self-test NG: step 形式でない呼び出しを見逃した"); ok = False

        # 中身があるのに1つも拾えないなら落ちる（偽の緑を出さない）
        if run("#!/bin/sh\nset -e\n" + "".join(
                f'echo "何かする {i}"\n' for i in range(8))) != 2:
            print("self-test NG: 何も拾えないのに『問題なし』を出した"); ok = False
        if run('step "存在しない段" "$PY" "$HARNESS/tools/nope.py"\n') != 1:
            print("self-test NG: 存在しない道具を通した"); ok = False

        # 行継続（\\ で改行）を読めること。読めないと道具を「外部」と誤分類し、
        # **全段を素通りさせて緑を返す**（2026-08-29 に自分で踏んだ）
        readme.write_text("（例外表なし）\n", encoding="utf-8")
        if run('step "継続の段" \\\n  "$PY" "$HARNESS/tools/bad.py"\n') != 1:
            print("self-test NG: 行継続を読めず、無検査の道具を通した"); ok = False
        if run('step "継続でよい段" \\\n  "$PY" "$HARNESS/tools/good.py"\n') != 0:
            print("self-test NG: 行継続でよい道具を落とした"); ok = False

    # 網羅の計測が**入れ子で呼ばれても外側を壊さない**こと。
    # この1件が無いと、内側の settrace(None) が外側の計測を止めて
    # **網羅の数字が黙って小さく出る**（2026-09-04 に実測。この道具自身が
    # 53% と表示していたが、実際には 27% までしか測れていなかった）
    def _noop(frame, ev, arg):
        return None
    sys.settrace(_noop)
    try:
        self_test_coverage(HERE / "figma_names.py")
        restored = sys.gettrace() is _noop
    finally:
        sys.settrace(None)
    if not restored:
        print("self-test NG: 網羅の計測が外側の追跡係を壊した"); ok = False

    ok = self_test_stages() and ok
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
