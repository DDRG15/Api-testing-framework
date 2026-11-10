/* Browser acceptance check; the optional renderer tools stay in a sandbox. */
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, rm} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {homedir} from 'node:os';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const options = new Map();
for (let index = 2; index < process.argv.length; index += 2) options.set(process.argv[index], process.argv[index + 1]);
if (!options.has('--tools')) throw new Error('Provide --tools pointing to a sandbox installation of Mermaid CLI.');
const tools = createRequire(join(resolve(options.get('--tools')), 'package.json'));
const {default: puppeteer} = await import(pathToFileURL(tools.resolve('puppeteer')).href);
const work = options.get('--work-dir') ?? join(homedir(), 'sandbox/enterprise-api-testing-framework/diagram-checks');
await mkdir(work, {recursive: true});
const profile = await mkdtemp(join(work, 'browser-'));
let browser;
try {
  browser = await puppeteer.launch({executablePath: options.get('--browser') ?? '/usr/bin/google-chrome',
    userDataDir: profile, headless: true, args: ['--no-sandbox', '--disable-background-networking']});
  const page = await browser.newPage();
  await page.setViewport({width: 1600, height: 1100});
  const errors = [];
  const external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!/^(file:|data:|about:)/.test(request.url())) external.push(request.url()); });
  const viewer = options.has('--viewer') ? pathToFileURL(resolve(options.get('--viewer'))).href
    : new URL('../docs/architecture.html', import.meta.url).href;
  await page.goto(viewer, {waitUntil: 'load'});
  const http = '#panel-0 [data-node-id="HTTP"]';
  await page.waitForSelector(http);
  const stats = () => page.evaluate(() => {
    const panel = document.querySelector('[role=tabpanel]:not([hidden])');
    return {
      incoming: panel.querySelectorAll('.edge-connection.is-incoming').length,
      outgoing: panel.querySelectorAll('.edge-connection.is-outgoing').length,
      selected: panel.querySelector('.node.is-selected')?.dataset.nodeId ?? null,
      status: panel.querySelector('.status').textContent,
    };
  });
  assert.equal((await stats()).selected, null);
  await page.hover(http);
  const hovered = await stats();
  assert.equal(hovered.selected, 'HTTP');
  assert(hovered.incoming > 0 && hovered.outgoing > 0);
  await page.waitForFunction(() => getComputedStyle(document.querySelector('#panel-0 .edge-connection.is-incoming')).stroke === 'rgb(88, 166, 255)', {timeout: 3000});
  const colors = await page.evaluate(() => ['incoming', 'outgoing'].map(direction => {
    const path = document.querySelector(`#panel-0 .edge-connection.is-${direction}`);
    const markerId = path.getAttribute('marker-end').match(/#([^)]*)\)/)[1];
    return [getComputedStyle(path).stroke, getComputedStyle(document.getElementById(markerId).querySelector('path')).fill];
  }));
  assert.deepEqual(colors, [['rgb(88, 166, 255)', 'rgb(88, 166, 255)'], ['rgb(255, 180, 84)', 'rgb(255, 180, 84)']]);
  await page.click(http);
  assert.equal(await page.$eval(http, node => node.getAttribute('aria-pressed')), 'true');
  await page.mouse.move(3, 3);
  assert.equal((await stats()).selected, 'HTTP');
  await page.hover('#panel-0 [data-node-id="Runner"]');
  assert.equal((await stats()).selected, 'Runner');
  await page.mouse.move(3, 3);
  assert.equal((await stats()).selected, 'HTTP');
  await page.keyboard.press('Escape');
  assert.equal((await stats()).selected, null);
  await page.$eval(http, node => node.focus());
  assert.equal(await page.$eval(http, node => document.activeElement === node), true);
  await page.keyboard.press('Enter');
  assert.equal(await page.$eval(http, node => node.getAttribute('aria-pressed')), 'true');
  await page.click('#panel-0 [data-action="clear"]');
  assert.equal((await stats()).selected, null);
  let zoomPanel = '#panel-0';
  if (await page.$('#tab-1')) {
    await page.click('#tab-1');
    await page.hover('#panel-1 [data-node-id="P4"]');
    const roadmap = await stats();
    assert.equal(roadmap.selected, 'P4');
    assert.equal(roadmap.incoming, 1);
    assert.equal(roadmap.outgoing, 2);
    await page.click('#panel-1 [data-node-id="P4"]');
    zoomPanel = '#panel-1';
  }
  await page.click(`${zoomPanel} [data-zoom="0.25"]`);
  assert.equal(await page.$eval(`${zoomPanel} svg`, svg => svg.style.width), '125%');
  await page.click(`${zoomPanel} [data-zoom="fit"]`);
  assert.equal(await page.$eval(`${zoomPanel} svg`, svg => svg.style.width), '100%');
  await page.click('#tab-0');
  await page.hover(http);
  await page.click(http);
  await page.mouse.move(3, 3);
  if (options.has('--screenshot')) await page.screenshot({path: options.get('--screenshot'), fullPage: true});
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  console.log('PASS: all rendered diagrams, hover, edge/arrowhead colors, pinned selection, temporary preview, keyboard, reset, zoom; no external requests.');
} finally {
  if (browser) await browser.close();
  await rm(profile, {recursive: true, force: true});
}
