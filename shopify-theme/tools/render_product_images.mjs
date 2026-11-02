// Render SVGs in a directory to PNG with Chromium. Bundle covers (which embed
// other covers as images) are rendered last.
import { createRequire } from 'node:module';
const require = createRequire(process.env.NODE_PATH.split(':')[0] + '/');
const { chromium } = require('playwright');
import fs from 'node:fs';
import path from 'node:path';

const dir = process.argv[2];
const outDir = process.argv[3];
fs.mkdirSync(outDir, { recursive: true });
const files = fs.readdirSync(dir).filter((f) => f.endsWith('.svg'));
const isBundle = (f) => f.includes('bundle');
const ordered = [...files.filter((f) => !isBundle(f)), ...files.filter(isBundle)];

const browser = await chromium.launch({ args: ['--allow-file-access-from-files'] });
for (const file of ordered) {
  const svg = fs.readFileSync(path.join(dir, file), 'utf8');
  const w = Number(svg.match(/width="(\d+)"/)[1]);
  const h = Number(svg.match(/height="(\d+)"/)[1]);
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  const htmlPath = path.join(dir, file.replace('.svg', '.html'));
  fs.writeFileSync(htmlPath, `<!doctype html><html><body style="margin:0">${svg}</body></html>`);
  await page.goto('file://' + htmlPath);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  const out = path.join(outDir, file.replace('.svg', '.png'));
  await page.screenshot({ path: out, clip: { x: 0, y: 0, width: w, height: h } });
  // bundles embed rendered covers from the svg dir
  if (!isBundle(file)) fs.copyFileSync(out, path.join(dir, file.replace('.svg', '.png')));
  console.log('rendered', path.basename(out));
  await page.close();
}
await browser.close();
