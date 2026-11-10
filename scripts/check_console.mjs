/* Real loopback console acceptance; optional Puppeteer installation stays in sandbox. */
import assert from 'node:assert/strict';
import {mkdir, mkdtemp, rm, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';

const args = new Map();
for (let i=2; i<process.argv.length; i+=2) args.set(process.argv[i], process.argv[i+1]);
if (!args.has('--tools') || !args.has('--work-dir')) throw new Error('Provide --tools and --work-dir sandbox paths.');
const url = new URL(process.env.CONSOLE_URL || '');
assert.equal(url.hostname, '127.0.0.1');
const tools = createRequire(join(resolve(args.get('--tools')), 'package.json'));
const {default:puppeteer} = await import(pathToFileURL(tools.resolve('puppeteer')).href);
const work = resolve(args.get('--work-dir'));
await mkdir(work, {recursive:true});
const profile = await mkdtemp(join(work, 'browser-'));
let browser;
try {
  browser = await puppeteer.launch({executablePath:args.get('--browser') || '/usr/bin/google-chrome', userDataDir:profile, headless:true, args:['--no-sandbox','--disable-background-networking']});
  const page = await browser.newPage();
  const errors=[],external=[];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith(url.origin) && !/^(data:|about:)/.test(request.url())) external.push(request.url()); });
  await page.setViewport({width:1600,height:1100});
  await page.goto(url.href);
  await page.waitForFunction(() => !document.querySelector('button.primary')?.disabled);
  assert.equal(await page.evaluate(() => location.hash), '');
  assert.equal((await fetch(`${url.origin}/api/runs`)).status,401);
  const clickText = async (selector,text) => {
    const handles = await page.$$(selector);
    for (const handle of handles) {
      const value = await handle.evaluate(node => node.textContent.trim());
      if (value === text) {await handle.click(); return;}
    }
    throw new Error(`Missing action: ${text}`);
  };
  await clickText('.check-option','Contract baseline'+ 'Compare the seven model schemas with their versioned baselines.');
  await clickText('button.primary','Run check');
  await page.waitForSelector('.drawer .status.passed',{timeout:30000});
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.querySelector('.drawer'));
  assert.equal(await page.$eval(':focus', node=>node.textContent.trim()),'Run check');
  await clickText('.nav-item','Evaluation');
  await clickText('button.primary','Evaluate sample');
  await page.waitForSelector('.drawer .status.passed',{timeout:30000});
  assert.match(await page.$eval('.drawer',node=>node.textContent),/4/);
  await page.keyboard.press('Escape');
  await clickText('.nav-item','History');
  assert((await page.$$('.journal-tile')).length >= 2);
  await page.click('.journal-tile');
  await page.waitForSelector('.drawer');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  assert(await page.$eval('.drawer',node=>node.contains(document.activeElement)));
  await page.keyboard.press('Escape');
  await clickText('.nav-item','Connect MCP');
  assert.match(await page.$eval('main',node=>node.textContent),/setup_mcp\.py/);
  await page.click('.host-option:nth-child(2)');
  assert.match(await page.$eval('.setup-card',node=>node.textContent),/--format codex/);
  assert.match(await page.$eval('.setup-card',node=>node.textContent),/mcp_servers\.api-testing-framework/);
  await page.click('.host-option:nth-child(1)');
  assert.match(await page.$eval('.setup-card',node=>node.textContent),/--format claude/);
  await clickText('.nav-item','Overview');
  await clickText('.check-option','Offline checks'+'Exercise retries, contracts, persistence, and controlled failures. No API credentials needed.');
  await clickText('button.primary','Run check');
  await page.waitForSelector('.drawer .status.passed',{timeout:60000});
  assert(await page.$eval('.detail-counts strong',node=>Number(node.textContent)>0));
  await page.keyboard.press('Escape');
  await page.screenshot({path:join(work,'desktop.png'),fullPage:true});
  await page.setViewport({width:390,height:844});
  assert(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:join(work,'mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
  await writeFile(join(work,'check.json'),JSON.stringify({contract_run:true,evaluation_run:true,offline_run:true,history_navigation:true,mcp_instructions:true,keyboard_and_focus:true,mobile_no_overflow:true,unauthenticated_api_rejected:true,external_requests:0,page_errors:errors},null,2)+'\n');
  console.log('PASS: real contract/evaluation jobs, summaries, history, MCP setup, keyboard/focus, responsive layout and session boundary; no external requests.');
} finally {
  if (browser) await browser.close();
  await rm(profile,{recursive:true,force:true});
}
