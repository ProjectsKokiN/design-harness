// 書き出し器のひな形が figma.mixed で落ちないかを実際に回して見る（#32・#10）。
//
// 実害（qnd-database・2026-09-03）: `strokeWeight` が figma.mixed（Symbol）を
// 返し、テンプレート文字列に入れた瞬間に書き出しが止まって
// **12部品のうち1件も取れなかった。**
//
// 走らせ方: node attack/preamble_test.mjs

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'exporters', '_preamble.js'), 'utf8');

// ひな形は `use_figma` に貼る前提で import できない。**そのまま評価する。**
const body = src.replace(/^const ALLOW_PAGES[^\n]*$/m, 'const ALLOW_PAGES = [];');
const load = new Function('figma', `${body}; return { val, num, revZ, h };`);

const MIXED = Symbol('figma.mixed');
const { val, num, revZ, h } = load({ mixed: MIXED, root: { children: [] } });

let ok = true;
const check = (cond, msg) => { if (!cond) { console.log(`NG: ${msg}`); ok = false; } };

// ── #32: mixed を文字列に入れても落ちない ────────────────────────────
const node = {
  strokeWeight: MIXED,          // 辺ごとに太さが違う
  cornerRadius: MIXED,
  opacity: 0.5,
  width: 12.345,
  name: 'Footer',
  get broken() { throw new Error('この getter は投げる'); },
};

check(val(node, 'strokeWeight') === 'MIXED', 'mixed を MIXED にしていない');
check(val(node, 'cornerRadius') === 'MIXED', 'cornerRadius の mixed を見ていない');
check(val(node, 'opacity') === 0.5, 'ふつうの値が変わった');
check(val(node, 'ない') === null, '無いキーが null でない');
check(val(node, 'broken') === null, '投げる getter で落ちた');
check(num(node, 'width') === 12.35, '数の丸めが違う');
check(num(node, 'strokeWeight') === 'MIXED', 'num が mixed を数に潰した');

// **文字列に入れて落ちないこと**が本題（実害そのものの形）
try {
  const line = `w=${num(node, 'width')}|sw=${val(node, 'strokeWeight')}`;
  check(line === 'w=12.35|sw=MIXED', `行の形が違う: ${line}`);
} catch (e) {
  check(false, `文字列にして落ちた: ${e.message}`);
}

// 素で書くと落ちることも見ておく（この道具が守っているものの確認）
let raw = null;
try { raw = `sw=${node.strokeWeight}`; } catch (e) { raw = 'THREW'; }
check(raw === 'THREW', '素の書き方が落ちない（この試験の前提が崩れている）');

// ── #10: 重なり順は生の真偽値のまま ──────────────────────────────
check(revZ({ itemReverseZIndex: true }) === true, 'true を返さない');
check(revZ({ itemReverseZIndex: false }) === false, 'false を返さない');
check(revZ({}) === null, '無いときに null を返さない');
check(revZ({ itemReverseZIndex: MIXED }) === null, 'mixed を真偽値にした');
// **意味に翻訳していないこと。** 'top' などに変えると、それが「正」になる
check(typeof revZ({ itemReverseZIndex: true }) === 'boolean',
      '重なり順を意味に翻訳している（生の値のままにする）');

// ── #26: インスタンスの寸法の上書きが行に出るか ──────────────────
{
  const frames = readFileSync(join(here, '..', 'exporters', 'export_frames.js'), 'utf8');
  const i = frames.indexOf("if (R(m.width) !== R(n.width)");
  check(i > 0, 'export_frames.js に寸法の上書きの判定が無い');
  // その場で同じ式を回して、行の形まで見る
  const R = (x) => (x == null ? null : Math.round(x * 100) / 100);
  const line = (m, n) =>
    (R(m.width) !== R(n.width) || R(m.height) !== R(n.height))
      ? 'override=' + R(m.width) + 'x' + R(m.height) + '->' + R(n.width) + 'x' + R(n.height)
      : null;
  check(line({ width: 48, height: 48 }, { width: 360, height: 360 })
        === 'override=48x48->360x360', '上書きの行の形が違う');
  check(line({ width: 48, height: 48 }, { width: 48, height: 48 }) === null,
        '同じ寸法なのに上書きと書いた');
  check(line({ width: 48, height: 48 }, { width: 48, height: 96 })
        === 'override=48x48->48x96', '高さだけの上書きを見ていない');
}

// ── 指紋が動くこと ──────────────────────────────────────────
check(h('a') !== h('b'), '指紋が別の文字列で同じ');
check(h('a') === h('a'), '指紋が同じ文字列で違う');

console.log(`preamble_test: ${ok ? 'OK' : 'NG'}（21 件）`);
process.exit(ok ? 0 : 1);
