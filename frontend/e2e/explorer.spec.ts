import { test, expect } from '@playwright/test';

test('load source comparison, highlight differences, filter and paginate',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await expect(page.getByRole('heading',{name:'Textual parallels'})).toBeVisible();
 await expect(page.locator('.passage')).toHaveCount(2);await expect(page.locator('mark.shared').first()).toBeVisible();
 await page.getByLabel('Match type',{exact:true}).selectOption('near');
 await expect(page.locator('.result-card').first()).toContainText('Near match');
 await expect(page.locator('mark.changed').first()).toBeVisible();
 await page.getByLabel('Show differences').uncheck();await expect(page.locator('mark.changed')).toHaveCount(0);
 await page.getByLabel('Show differences').check();await expect(page.locator('mark.changed').first()).toBeVisible();
 await page.getByLabel('Document pair').selectOption('mark,matthew');
 await expect(page.locator('.comparison-heading')).toContainText('Mark');await expect(page.locator('.comparison-heading')).toContainText('Matthew');
 await page.getByLabel('Next page').click();await expect(page.locator('.pagination')).toContainText('25–');
 await page.getByLabel('Search passages').fill('no-result-unique-xyz');await expect(page.getByText('No matching passages')).toBeVisible();
 await page.getByRole('button',{name:'Clear filters'}).click();await expect(page.locator('.passage')).toHaveCount(2);
 expect(errors).toEqual([]);
});

test('review survives reload and analysis without duplicate results',async({page,request})=>{
 await page.goto('/');await expect(page.locator('.passage')).toHaveCount(2);
 const id=new URL(page.url()).searchParams.get('parallel')!;
 const before=(await (await request.get('/api/stats')).json()).counts.total;
 const original=await (await request.get('/api/parallels/'+id)).json();
 try{
 await page.getByLabel('Review note').fill('E2E: checked against the source.');await page.getByRole('button',{name:'Accept',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Review saved');
 await page.reload();await expect(page.getByLabel('Review note')).toHaveValue('E2E: checked against the source.');await expect(page.locator('.comparison-heading')).toContainText('Accepted');
 await page.getByRole('button',{name:'Run analysis',exact:true}).click();await expect(page.getByRole('progressbar',{name:'Preparation progress'})).toBeVisible();await expect(page.getByRole('status')).toContainText('Analysis complete',{timeout:30000});
 const after=(await (await request.get('/api/stats')).json()).counts.total;expect(after).toBe(before);
 const d=await (await request.get('/api/parallels/'+id)).json();expect(d.status).toBe('accepted');expect(d.note).toBe('E2E: checked against the source.');
 await page.getByLabel('Review status',{exact:true}).selectOption('accepted');await expect(page.locator('.result-card').first()).toContainText('accepted');
 const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'Export CSV'}).click();const download=await downloadPromise;expect(download.suggestedFilename()).toBe('parallels.csv');
 }finally{await request.patch('/api/parallels/'+id+'/review',{data:{status:original.status,note:original.note}})}
});

test('unsaved note protection, deep-link selection, loading and error recovery',async({page})=>{
 await page.goto('/');await expect(page.locator('.passage')).toHaveCount(2);
 await page.getByLabel('Review note').fill('Unsaved note');page.once('dialog',dialog=>dialog.dismiss());
 await page.locator('.result-card').nth(1).click();await expect(page.getByLabel('Review note')).toHaveValue('Unsaved note');
 page.once('dialog',dialog=>dialog.accept());await page.locator('.result-card').nth(1).click();await expect(page.getByLabel('Review note')).toHaveValue('');
 await page.getByLabel('Next page').click();await expect(page.locator('.pagination')).toContainText('25–');
 await page.locator('.result-card').nth(2).click();await expect(page.locator('.passage')).toHaveCount(2);
 const url=page.url();const heading=await page.locator('.comparison-heading h2').innerText();
 await page.goto(url);await expect(page.locator('.comparison-heading h2')).toHaveText(heading);
 await page.route('**/api/parallels?**',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Temporary analysis service error'})}));
 await page.getByLabel('Match type',{exact:true}).selectOption('near');await expect(page.getByRole('alert')).toContainText('Temporary analysis service error');
 await page.unroute('**/api/parallels?**');await page.getByRole('button',{name:'Dismiss error'}).click();await page.getByLabel('Match type',{exact:true}).selectOption('exact');await expect(page.locator('.result-card').first()).toContainText('Exact match');
});

test('corpus provenance, method coverage, keyboard controls and mobile layout',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Corpus',exact:true}).click();await expect(page.locator('.document-card')).toHaveCount(3);
 await page.getByRole('button',{name:'Method & runs',exact:true}).click();await expect(page.getByRole('heading',{name:'How matches are found'})).toBeVisible();await expect(page.locator('tbody tr')).toHaveCount(3);
 await page.getByRole('button',{name:/^Parallels/}).click();await expect(page.locator('.passage')).toHaveCount(2);
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await expect(page.getByLabel('Search passages')).toBeVisible();await page.getByLabel('Search passages').focus();await page.keyboard.type('bread');
 await expect(page.locator('.result-card').first()).toContainText(/bread/i);
 await page.screenshot({path:'test-results/mobile.png',fullPage:true});
 await page.setViewportSize({width:1440,height:1100});await page.getByLabel('Search passages').fill('');
 await expect(page.locator('.passage')).toHaveCount(2);await page.screenshot({path:'test-results/desktop.png',fullPage:true});
});

test('semantic suggestions filter, compare, persist review and remain usable on mobile',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const initial=await (await request.get('/api/semantic?limit=1')).json();expect(initial.total).toBeGreaterThan(0);const first=initial.items[0];
 try{
 await page.goto('/');await page.getByRole('button',{name:'Semantic suggestions',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Semantic suggestions',exact:true})).toBeVisible();
 await expect(page.locator('.passage')).toHaveCount(2);await expect(page.locator('.evidence')).toContainText('Cosine similarity');
 await expect(page.locator('.semantic-intro')).toContainText('computed locally');
 await page.getByRole('button',{name:'Accept suggestion',exact:true}).click();await expect(page.locator('.comparison-heading')).toContainText('accepted');
 await page.reload();await page.getByRole('button',{name:'Semantic suggestions',exact:true}).click();await expect(page.locator('.comparison-heading')).toContainText('accepted');
 await page.getByLabel('Semantic review status').selectOption('accepted');await expect(page.locator('.result-card').first()).toContainText('accepted');
 await page.getByLabel('Semantic review status').selectOption('');
 await page.getByLabel('Semantic document pair').selectOption('mark,matthew');await expect(page.locator('.comparison-heading')).toContainText('mark & matthew');
 await page.getByLabel('Minimum cosine').selectOption('.9');await expect(page.locator('.passage')).toHaveCount(2);
 await page.getByLabel('Minimum cosine').selectOption('.65');await page.getByLabel('Next semantic page').click();await expect(page.locator('.pagination')).toContainText('25–');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.screenshot({path:'../docs/screenshot-semantic-mobile.png',fullPage:true});
 await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>window.scrollTo(0,0));await expect(page.getByRole('heading',{name:'Semantic suggestions',exact:true})).toBeVisible();await page.screenshot({path:'../docs/screenshot-semantic-desktop.png',fullPage:false});
 expect(errors).toEqual([]);
 }finally{await request.patch('/api/semantic/'+first.id+'/review',{data:{status:first.status,note:first.note}})}
});


test('skip-seed result exposes evidence, word differences and run counters',async({page,request})=>{
 const stats=await (await request.get('/api/stats')).json();
 expect(stats.algorithm).toBe('lexical-1.1.0');expect(stats.run.config.use_skip_seeds).toBe(true);
 expect(stats.run.pairs.every((p:{skip_seeds:number})=>p.skip_seeds>0)).toBeTruthy();
 let match;
 for(let offset=0;offset<stats.counts.total;offset+=100){
  const result=await (await request.get('/api/parallels?limit=100&offset='+offset)).json();
  match=result.items.find((m:{method:string})=>m.method==='skip-seed-local-alignment');if(match)break;
 }
 expect(match).toBeTruthy();
 await page.goto('/?parallel='+match.id);
 await expect(page.locator('.evidence')).toContainText('bounded skips');
 await expect(page.locator('.passage')).toHaveCount(2);await expect(page.locator('mark.changed').first()).toBeVisible();
 await page.getByRole('button',{name:'Method & runs',exact:true}).click();
 await expect(page.locator('thead')).toContainText('consecutive / skip');
 await expect(page.getByText('allowing one intervening word per step',{exact:false})).toBeVisible();
});

test('workspace adapts from compact phones to ultrawide monitors across every view',async({page})=>{
 test.setTimeout(60000);
 await page.goto('/');await expect(page.locator('.passage')).toHaveCount(2);
 for(const width of [320,390,768,1024,1440,1920,2560,3440]){
  await page.setViewportSize({width,height:1000});
  for(const view of ['Parallels','Semantic suggestions','Corpus','Method & runs']){
   await page.getByRole('button',{name:view==='Parallels'?/^Parallels/:view,exact:view!=='Parallels'}).click();
   if(view==='Parallels'||view==='Semantic suggestions')await expect(page.locator('.passage')).toHaveCount(2);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),`${view} at ${width}px`).toBeTruthy();
   const main=await page.locator('.main').boundingBox();expect(main).not.toBeNull();
   expect(main!.x+main!.width,`available width at ${width}px`).toBeGreaterThanOrEqual(width-2);
   if(view==='Parallels'||view==='Semantic suggestions'){
    const passages=await page.locator('.passage').all();
    const first=(await passages[0].boundingBox())!,second=(await passages[1].boundingBox())!;
    if(width>=1440)expect(second.x).toBeGreaterThan(first.x+first.width-2);
    if(width<=1250)expect(second.y).toBeGreaterThan(first.y);
    await page.getByRole('heading',{name:'Researcher review',exact:true}).scrollIntoViewIfNeeded();
    await expect(page.getByRole('heading',{name:'Researcher review',exact:true})).toBeVisible();
   }
  }
 }
 await page.setViewportSize({width:3440,height:1440});await page.getByRole('button',{name:/^Parallels/}).click();
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'test-results/ultrawide.png',fullPage:true});
});

test('preparation shows real progress states, handles retry, and opens the workspace',async({page})=>{
 let state={status:'preparing',phase:'model',message:'Loading the local model',percent:null as number|null,error:null as string|null};
 await page.route('**/api/startup',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(state)}));
 await page.route('**/api/startup/retry',route=>{
  state={status:'preparing',phase:'encoding',message:'Encoding passages: 64 of 128',percent:60,error:null};
  return route.fulfill({status:202,contentType:'application/json',body:'{"status":"preparing"}'});
 });
 await page.goto('/');await expect(page.getByRole('heading',{name:'Preparing your workspace'})).toBeVisible();
 const progress=page.getByRole('progressbar',{name:'Preparation progress'});
 await expect(progress).not.toHaveAttribute('aria-valuenow');
 state={status:'preparing',phase:'encoding',message:'Encoding passages: 64 of 128',percent:60,error:null};
 await expect(progress).toHaveAttribute('aria-valuenow','60');
 await expect(page.getByRole('status')).toContainText('64 of 128');
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.screenshot({path:'test-results/preparation-mobile.png',fullPage:true});
 await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'../docs/preparation.png',fullPage:true});
 state={status:'failed',phase:'failed',message:'Preparation failed',percent:null,error:'Check the internet connection, then retry.'};
 await expect(page.getByRole('alert')).toContainText('internet connection');
 await page.getByRole('button',{name:'Retry preparation'}).click();
 await expect(progress).toHaveAttribute('aria-valuenow','60');
 state={status:'ready',phase:'ready',message:'Ready',percent:100,error:null};
 await expect(page.getByRole('heading',{name:'Textual parallels'})).toBeVisible();await expect(page.locator('.passage')).toHaveCount(2);
 await expect(page.getByRole('heading',{name:'Preparing your workspace'})).toHaveCount(0);
});
