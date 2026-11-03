// WebKitとChromiumで実際のスクロールとSVG描画を試す（#168）。
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { chromium, webkit } from 'playwright';

export async function check(config) {
  const results=[];
  if(!Array.isArray(config.pages)||!config.pages.length) throw new Error('pagesがありません（対象0件）');
  for(const [name,type] of [['chromium',chromium],['webkit',webkit]]) {
    let browser;
    try {
      browser=await type.launch({headless:true,...(name==='chromium'&&config.chromiumChannel?{channel:config.chromiumChannel}:{})});
      for(const entry of config.pages) {
        const page=await browser.newPage({viewport:config.viewport??{width:1280,height:900}});
        try {
          await page.goto(entry.url,{waitUntil:'networkidle'});
          if(!Array.isArray(entry.scroll)||!entry.scroll.length||!Array.isArray(entry.vectors)||!entry.vectors.length)
            throw new Error('scrollとvectorsの対象が必要です（宣言が空なら未検証）');
          for(const selector of entry.scroll) {
            const node=page.locator(selector);
            if(await node.count()!==1) throw new Error(`スクロール対象が1件ではありません: ${selector}`);
            await node.hover();
            const before=await node.evaluate(n=>({y:n.scrollTop,overflow:n.scrollHeight>n.clientHeight}));
            if(!before.overflow) throw new Error(`スクロールする中身がありません: ${selector}`);
            await page.mouse.wheel(0,400);
            await page.waitForFunction(({selector,y})=>document.querySelector(selector).scrollTop!==y,{selector,y:before.y},{timeout:3000});
            results.push({browser:name,channel:name==='chromium'?(config.chromiumChannel??'bundled'): 'bundled',url:entry.url,selector,kind:'scroll',status:'checked'});
          }
          for(const selector of entry.vectors) {
            const node=page.locator(selector);
            if(await node.count()!==1) throw new Error(`VECTOR対象が1件ではありません: ${selector}`);
            await node.scrollIntoViewIfNeeded();
            const box=await node.boundingBox();
            if(!box||box.width<=0||box.height<=0) throw new Error(`VECTORの領域がありません: ${selector}`);
            const before=await page.screenshot({clip:box,animations:'disabled'});
            const original=await node.evaluate(n=>({value:n.style.getPropertyValue('visibility'),priority:n.style.getPropertyPriority('visibility')}));
            let after;
            try {
              await node.evaluate(n=>n.style.setProperty('visibility','hidden','important'));
              after=await page.screenshot({clip:box,animations:'disabled'});
            } finally {
              await node.evaluate((n,o)=>{if(o.value)n.style.setProperty('visibility',o.value,o.priority);else n.style.removeProperty('visibility');},original);
            }
            const pixels=await page.evaluate(async({a,b})=>{
              const load=s=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src='data:image/png;base64,'+s;});
              const [x,y]=await Promise.all([load(a),load(b)]);
              const c=document.createElement('canvas');c.width=x.width;c.height=x.height;
              const ctx=c.getContext('2d');ctx.drawImage(x,0,0);const d=ctx.getImageData(0,0,c.width,c.height).data;
              ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(y,0,0);const e=ctx.getImageData(0,0,c.width,c.height).data;
              let changed=0;for(let i=0;i<d.length;i+=4)if(d[i]!==e[i]||d[i+1]!==e[i+1]||d[i+2]!==e[i+2]||d[i+3]!==e[i+3])changed++;
              return changed;
            },{a:before.toString('base64'),b:after.toString('base64')});
            if(!pixels) throw new Error(`VECTORを隠しても画素が変わりません（描画を確認できません）: ${selector}`);
            results.push({browser:name,url:entry.url,selector,kind:'vector',status:'checked',changedPixels:pixels});
          }
        } catch(e) {
          results.push({browser:name,url:entry.url,status:'failed',why:String(e)});
        } finally {await page.close();}
      }
    } catch(e) {
      results.push({browser:name,status:'unverified',why:String(e)});
    } finally {if(browser)await browser.close();}
  }
  return {results,limits:['Safariの操作バー・iOS実機・ネイティブSafariは未検証です','指定した画面・スクロール対象・VECTOR以外は未検証です']};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  try {
    const result=await check(JSON.parse(await readFile(process.argv[2],'utf8')));
    process.stdout.write(JSON.stringify(result,null,2)+'\n');
    process.exitCode=result.results.some(r=>r.status==='unverified')?2:result.results.some(r=>r.status==='failed')?1:0;
  } catch(e) {process.stderr.write(String(e)+'\n');process.exitCode=2;}
}
