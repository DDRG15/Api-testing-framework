/* Exercise actual Connections forms against the explicit loopback fixture. */
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
const options=new Map();
for(let i=2;i<process.argv.length;i+=2)options.set(process.argv[i],process.argv[i+1]);
const tools=createRequire(join(resolve(options.get('--tools')),'package.json'));
const puppeteer=tools('puppeteer');
const work=resolve(options.get('--work-dir'));
await mkdir(work,{recursive:true});
const profile=await mkdtemp(join(work,'browser-'));
const url=new URL(process.env.CONSOLE_URL);
assert.equal(url.hostname,'127.0.0.1');
assert.equal(new URL(process.env.TARGET_URL).hostname,'127.0.0.1');
const secret='synthetic-browser-session-secret';
let browser;
try {
 browser=await puppeteer.launch({executablePath:'/usr/bin/google-chrome',headless:true,userDataDir:profile,args:['--no-sandbox','--disable-background-networking']});
 const page=await browser.newPage(), errors=[],external=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(!r.url().startsWith(url.origin)&&!r.url().startsWith('data:'))external.push(r.url());});
 await page.setViewport({width:1500,height:1100});
 await page.goto(url.href);
 await page.waitForFunction(()=>!document.querySelector('button.primary')?.disabled);
 await page.evaluate(()=>[...document.querySelectorAll('.nav-item')].find(n=>n.textContent==='Connections').click());
 await page.waitForSelector('.connection-card');
 const target='.connection-card:nth-of-type(1)';
 await page.type(`${target} input[type=url]`,process.env.TARGET_URL+'/health');
 await page.select(`${target} select`,'bearer');
 await page.type(`${target} input[type=password]`,secret);
 await page.click(`${target} button[type=submit]`);
 await page.waitForFunction(()=>document.querySelector('.connection-notice')?.textContent.includes('Saved'));
 assert.equal(await page.$eval(`${target} input[type=password]`,n=>n.value),'');
 await page.evaluate(()=>[...document.querySelectorAll('.connection-actions button')].find(n=>n.textContent==='Check target').click());
 await page.waitForSelector('.drawer .status.passed',{timeout:15000});
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.querySelector('.drawer'));
 await page.type(`${target} input[type=url]`,'/changed-draft');
 assert(await page.$eval(`${target} .connection-actions button:nth-child(2)`,n=>n.disabled));
 for(let index=0;index<2;index++) {
  const form=(await page.$$('.provider-form'))[index];
  await (await form.$('input')).type(secret);
  await (await form.$('button[type=submit]')).click();
  await page.waitForFunction(i=>document.querySelectorAll('.provider-form')[i].querySelector('.tag').textContent==='Configured in memory',{},index);
  assert.equal(await (await form.$('input')).evaluate(n=>n.value),'');
  const buttons=await form.$$('button'); await buttons[1].click();
  await page.waitForSelector('.drawer .status.passed',{timeout:15000});
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('.drawer'));
 }
 const storage=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));
 assert(!storage.includes(secret));
 assert(!(await page.content()).includes(secret));
 await page.screenshot({path:join(work,'connections-desktop.png'),fullPage:true});
 await page.setViewport({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:join(work,'connections-mobile.png'),fullPage:true});
 await page.evaluate(()=>[...document.querySelectorAll('button')].find(n=>n.textContent==='Disconnect all connections').click());
 await page.waitForFunction(()=>[...document.querySelectorAll('.connection-card .tag')].filter(n=>n.textContent==='Configured in memory').length===0);
 assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
 await writeFile(join(work,'check.json'),JSON.stringify({real_target_get:true,provider_catalogs_loopback_only:true,password_fields_cleared:true,unsaved_target_cannot_run:true,no_key_in_browser_storage:true,disconnect_all:true,mobile_no_overflow:true,page_errors:errors,external_browser_requests:0},null,2)+'\n');
 console.log('PASS: Connections saves, target/schema check, two synthetic provider catalogs, disconnect and browser-secret boundaries.');
} finally {
 if(browser)await browser.close();
 await rm(profile,{recursive:true,force:true});
}
