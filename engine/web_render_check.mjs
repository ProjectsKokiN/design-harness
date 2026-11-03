// 表示した画面を、画像ではなく数値で点検する（候補1・#176・#177・2026-11-03）。
//
// - 候補1: 文字が枠に切られる・他の要素に隠れる・自分の枠からはみ出す・数字と単位が別の行に分かれる・壊れた画像
// - #176: **動きを有効にしたまま**、読み込み直後・スクロールで現れた後・ホバーの後に
//   「隠れたままの画像・字」「一度見えてから消える（一瞬消える）」「途中で打ち切られた動き」を数える
//   （それまでの段は prefers-reduced-motion: reduce で測っていて、動きの状態を一度も見ていなかった）
// - #177: 同じ幅で**2つ以上の高さ**を測り、要素どうしの間隔（Figma の値）と重なりを比べる
//
// 判定は getBoundingClientRect・getComputedStyle・elementFromPoint・アニメーションのイベントだけで行う。
// **画像の見比べで合否を決めない**（見た目の評価はデザイナー本人）。
// 終了コード: 0 合格・1 確かめて違反・2 確かめられなかった（ブラウザが無い・動きが落ち着かない・宣言が足りない）。
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { chromium, webkit } from 'playwright';

const CHECKS=['clipped','occluded','spill','unitWrap','brokenImage','hidden','flash','cancel','gap','overlap'];
const MIN_FRAMES=4;   // 動きの記録がこれより少なければ「見ていない」（stageshow の判定に倣う）

// ページの中に入れる記録係。読み込みの最初から動く
const INIT=`(() => {
  const S = window.__hr = {cancels: [], frames: 0, flashes: [], sampling: true};
  const desc = el => el.getAttribute && (el.getAttribute('data-layout-id') ? '[data-layout-id="'+el.getAttribute('data-layout-id')+'"]'
    : el.id ? '#'+el.id : el.tagName.toLowerCase() + (el.classList && el.classList.length ? '.'+[...el.classList].join('.') : ''));
  S.desc = desc;
  // 読み込みに失敗した画像。WebKit は complete・naturalWidth の報せ方が Chromium と違うので、失敗の通知でも数える
  S.broken = new WeakSet();
  document.addEventListener('error', e => { if (e.target && e.target.tagName === 'IMG') S.broken.add(e.target); }, true);
  for (const t of ['animationcancel', 'transitioncancel'])
    document.addEventListener(t, e => S.cancels.push({type: t, target: desc(e.target), name: e.animationName || e.propertyName || ''}), true);
  const opacity = el => { let o = 1; for (let n = el; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity); return o; };
  S.opacity = opacity;
  const state = new WeakMap();
  const tick = () => {
    if (!S.sampling) return;
    S.frames++;
    const els = document.querySelectorAll('img, svg, [data-render-watch]');
    let i = 0;
    for (const el of els) {
      if (++i > 400) break;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0 || r.bottom < 0 || r.top > innerHeight) continue;
      const o = opacity(el) * (getComputedStyle(el).visibility === 'hidden' ? 0 : 1);
      const s = state.get(el) || {seen: false, dipped: false};
      if (o > 0.5) { if (s.dipped) S.flashes.push(desc(el)); s.seen = true; s.dipped = false; }
      else if (o < 0.05 && s.seen) s.dipped = true;
      state.set(el, s);
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();`;

// 画面の中で集める。allow は {check, selector} の配列
function collect(allow) {
  const S = window.__hr, desc = S.desc, out = [];
  const allowed = (check, el) => allow.some(a => a.check === check && el.closest(a.selector));
  const push = (check, el, detail) => { if (!allowed(check, el)) out.push({check, target: desc(el), detail}); };
  const vw = innerWidth, vh = innerHeight;
  const shown = el => { const cs = getComputedStyle(el); return cs.display !== 'none' && !el.closest('[aria-hidden="true"]'); };
  const inView = r => r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  const textEls = [...document.body.querySelectorAll('*')].filter(el =>
    !['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName) && shown(el)
    && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
  for (const el of textEls) {
    const r = el.getBoundingClientRect();
    if (!inView(r)) continue;
    const cs = getComputedStyle(el);
    // 自分の枠からはみ出す（自分では切っていない）
    if (cs.display !== 'inline' && cs.overflowX === 'visible' && cs.overflowY === 'visible'
        && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) && el.clientWidth > 0)
      push('spill', el, `中身 ${el.scrollWidth}×${el.scrollHeight} / 枠 ${el.clientWidth}×${el.clientHeight}`);
    // 祖先に切られる（スクロールする箱は除く）
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      const pc = getComputedStyle(p);
      const cx = ['hidden', 'clip'].includes(pc.overflowX), cy = ['hidden', 'clip'].includes(pc.overflowY);
      if (!cx && !cy) continue;
      const q = p.getBoundingClientRect();
      const over = Math.max(cx ? Math.max(q.left - r.left, r.right - q.right) : 0, cy ? Math.max(q.top - r.top, r.bottom - q.bottom) : 0);
      if (over > 0.5) { push('clipped', el, `${over.toFixed(1)}px 切られている（${desc(p)}）`); break; }
    }
    // 他の要素に隠れる（各行の中心で当たり判定）
    const range = document.createRange();
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      range.selectNodeContents(n);
      for (const line of range.getClientRects()) {
        const x = line.left + line.width / 2, y = line.top + line.height / 2;
        if (x < 0 || y < 0 || x >= vw || y >= vh) continue;
        const hit = document.elementFromPoint(x, y);
        if (hit && hit !== el && !el.contains(hit) && !hit.contains(el)) {
          push('occluded', el, `${desc(hit)} の下になっている`); break;
        }
      }
    }
    // 数字と単位が別の行に分かれる
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const map = []; let text = '';
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.parentElement !== el) continue;
      for (let i = 0; i < n.textContent.length; i++) map.push([n, i]);
      text += n.textContent;
    }
    const rx = /(\d)[\s ]*(?=([%％円年月日時分秒個件回人歳倍kKmMgGpxPX]))/g;
    for (let m; (m = rx.exec(text));) {
      const a = map[m.index], bi = text.indexOf(m[2], m.index + 1), b = map[bi];
      if (!a || !b) continue;
      const ra = document.createRange(); ra.setStart(a[0], a[1]); ra.setEnd(a[0], a[1] + 1);
      const rb = document.createRange(); rb.setStart(b[0], b[1]); rb.setEnd(b[0], b[1] + 1);
      const ya = ra.getBoundingClientRect(), yb = rb.getBoundingClientRect();
      if (ya.height && yb.height && Math.abs(yb.top - ya.top) > ya.height / 2) {
        push('unitWrap', el, `「${m[1]}」と「${m[2]}」が別の行`); break;
      }
    }
  }
  // 隠れたままの画像・字、壊れた画像
  for (const el of [...document.querySelectorAll('img, svg, [data-render-watch]'), ...textEls]) {
    const r = el.getBoundingClientRect();
    if (!shown(el)) continue;
    // 壊れた画像は大きさで見ない。WebKit は alt が空の壊れた画像を 0×0 に潰す（2026-11-03 実測）
    if (el.tagName === 'IMG' && (S.broken.has(el) || (el.complete && el.naturalWidth === 0))) {
      push('brokenImage', el, el.getAttribute('src') || '');
      continue;
    }
    if (!inView(r)) continue;
    const o = S.opacity(el) * (getComputedStyle(el).visibility === 'hidden' ? 0 : 1);
    if (o < 0.05) push('hidden', el, `見えない（不透明度 ${o.toFixed(2)}）`);
  }
  // 動きのイベントは要素ではなく名前で残るので、許可は名前で突き合わせる
  const allowedName = (check, d) => allow.some(a => a.check === check
    && [...document.querySelectorAll(a.selector)].some(el => desc(el) === d));
  for (const c of S.cancels) if (!allowedName('cancel', c.target)) out.push({check: 'cancel', target: c.target, detail: `${c.type} ${c.name}`});
  for (const t of new Set(S.flashes)) if (!allowedName('flash', t)) out.push({check: 'flash', target: t, detail: '一度見えてから消えた'});
  S.cancels = []; S.flashes = [];
  return out;
}

async function settle(page, ms) {
  // 有限の動きが走り終わるまで待つ（繰り返し続ける飾りの動きは待たない）
  try {
    await page.waitForFunction(() => document.getAnimations().every(a => {
      if (a.playState !== 'running') return true;
      const t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
      return t && t.endTime === Infinity;
    }), null, {timeout: ms, polling: 50});
    await page.waitForTimeout(100);
    return true;
  } catch { return false; }
}

function validate(config) {
  if (!Array.isArray(config.pages) || !config.pages.length) throw new Error('pages がありません（対象0件）');
  for (const p of config.pages) {
    if (!p.url) throw new Error('url の無い page があります');
    const vps = p.viewports ?? [];
    if (vps.length < 2) throw new Error(`${p.url}: viewports は2つ以上（同じ幅で高さを変えたもの）が必要です（#177）`);
    const byWidth = new Map();
    for (const v of vps) byWidth.set(v.width, (byWidth.get(v.width) ?? new Set()).add(v.height));
    if (![...byWidth.values()].some(h => h.size >= 2))
      throw new Error(`${p.url}: 同じ幅で高さだけを変えた viewport が2つ以上ありません（#177）`);
    for (const a of p.allow ?? []) {
      if (!CHECKS.includes(a.check) || !a.selector) throw new Error(`${p.url}: allow の check か selector が不正です: ${JSON.stringify(a)}`);
      if (!a.why || !String(a.why).trim()) throw new Error(`${p.url}: allow に理由（why）がありません: ${a.selector}`);
    }
    for (const g of p.gaps ?? []) if (!g.a || !g.b || typeof g.gap !== 'number') throw new Error(`${p.url}: gaps の a・b・gap が不正です`);
  }
}

export async function check(config) {
  validate(config);
  const settleMs = config.settleMs ?? 5000;
  const results = [];
  const browsers = config.browsers ?? ['chromium', 'webkit'];
  for (const [name, type] of [['chromium', chromium], ['webkit', webkit]].filter(([n]) => browsers.includes(n))) {
    let browser;
    try {
      browser = await type.launch({headless: true, ...(name === 'chromium' && config.chromiumChannel ? {channel: config.chromiumChannel} : {})});
      for (const p of config.pages) {
        const allow = (p.allow ?? []).map(a => ({check: a.check, selector: a.selector}));
        for (const vp of p.viewports) {
          const where = {browser: name, url: p.url, viewport: `${vp.width}x${vp.height}`};
          const ctx = await browser.newContext({viewport: vp, reducedMotion: 'no-preference'});
          const page = await ctx.newPage();
          try {
            await page.addInitScript(INIT);
            await page.goto(p.url, {waitUntil: 'load'});
            if (!await settle(page, settleMs)) { results.push({...where, status: 'unverified', why: `${settleMs}ms たっても動きが落ち着きません（測れません）`}); continue; }
            // 動きの無いページは一瞬で落ち着くので、記録が最低枚数たまるまで待つ
            await page.waitForFunction(n => window.__hr.frames >= n, MIN_FRAMES, {timeout: 2000}).catch(() => {});
            const frames = await page.evaluate(() => window.__hr.frames);
            if (frames < MIN_FRAMES) { results.push({...where, status: 'unverified', why: `動きの記録が ${frames} 枚しかありません（見ていません）`}); continue; }
            const findings = [];
            const add = (phase, list) => findings.push(...list.map(f => ({...f, phase})));
            add('読み込み直後', await page.evaluate(collect, allow));
            // スクロールで現れるもの（下にあるもの）も、止まった状態で数える
            const height = await page.evaluate(() => document.documentElement.scrollHeight);
            for (let y = vp.height; y < height; y += vp.height) {
              await page.evaluate(v => window.scrollTo(0, v), y);
              await settle(page, settleMs);
              add(`スクロール ${y}px`, (await page.evaluate(collect, allow)).filter(f => !['occluded'].includes(f.check)));
            }
            await page.evaluate(() => window.scrollTo(0, 0));
            await settle(page, settleMs);
            for (const sel of p.hover ?? []) {
              const node = page.locator(sel).first();
              if (!await node.count()) { results.push({...where, status: 'failed', kind: 'hover', why: `ホバーの対象がありません: ${sel}`}); continue; }
              await node.scrollIntoViewIfNeeded();
              await node.hover();
              await settle(page, settleMs);
              await page.mouse.move(0, 0);
              await settle(page, settleMs);
              add(`ホバーの後（${sel}）`, await page.evaluate(collect, allow));
            }
            // 要素どうしの間隔と重なり（高さごとに測る・#177）
            await page.evaluate(() => window.scrollTo(0, 0));
            for (const g of p.gaps ?? []) {
              const m = await page.evaluate(({a, b, axis}) => {
                const A = document.querySelector(a), B = document.querySelector(b);
                if (!A || !B) return null;
                const ra = A.getBoundingClientRect(), rb = B.getBoundingClientRect();
                return axis === 'x' ? rb.left - ra.right : rb.top - ra.bottom;
              }, {a: g.a, b: g.b, axis: g.axis ?? 'y'});
              if (m === null) { findings.push({check: 'gap', target: `${g.a} → ${g.b}`, detail: '要素がありません', phase: '間隔'}); continue; }
              if (Math.abs(m - g.gap) > (g.tolerance ?? 1)) findings.push({check: 'gap', target: `${g.a} → ${g.b}`, detail: `間隔 ${m.toFixed(1)}px（Figma ${g.gap}px）`, phase: '間隔'});
            }
            for (const [a, b] of p.noOverlap ?? []) {
              const area = await page.evaluate(({a, b}) => {
                const A = document.querySelector(a), B = document.querySelector(b);
                if (!A || !B) return -1;
                const ra = A.getBoundingClientRect(), rb = B.getBoundingClientRect();
                return Math.max(0, Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left)) * Math.max(0, Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top));
              }, {a, b});
              if (area !== 0) findings.push({check: 'overlap', target: `${a} × ${b}`, detail: area < 0 ? '要素がありません' : `${area.toFixed(0)}px² 重なっている`, phase: '重なり'});
            }
            for (const f of findings) results.push({...where, status: 'failed', ...f});
            results.push({...where, status: 'checked', findings: findings.length, frames});
          } catch (e) {
            results.push({...where, status: 'failed', why: String(e)});
          } finally { await ctx.close(); }
        }
      }
    } catch (e) {
      results.push({browser: name, status: 'unverified', why: String(e)});
    } finally { if (browser) await browser.close(); }
  }
  return {results, limits: [
    '他の要素に隠れるかは、スクロールしていない最初の画面だけで見ています（固定の見出しがスクロール中に重なるのは対象外）',
    'ホバーは宣言した要素だけ、高さは宣言した viewport だけを見ています',
    'Safari の操作バー・iOS 実機は見ていません',
  ]};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const result = await check(JSON.parse(await readFile(process.argv[2], 'utf8')));
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
    process.exitCode = result.results.some(r => r.status === 'unverified') ? 2 : result.results.some(r => r.status === 'failed') ? 1 : 0;
  } catch (e) { process.stderr.write(String(e) + '\n'); process.exitCode = 2; }
}
