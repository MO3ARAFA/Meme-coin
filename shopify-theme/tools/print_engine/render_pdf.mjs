// Render Hroofy interior HTML files to vector PDFs with Chromium (Playwright).
// Usage: node render_pdf.mjs '<json array of {html, pdf, width, height, pages}>'
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';

function loadPlaywright() {
  const roots = [process.cwd() + '/', ...(process.env.NODE_PATH || '').split(':').filter(Boolean).map((p) => p + '/')];
  try {
    roots.push(execFileSync('npm', ['root', '-g']).toString().trim() + '/');
  } catch {
    /* npm not on PATH */
  }
  for (const root of roots) {
    try {
      return createRequire(root)('playwright');
    } catch {
      /* try next */
    }
  }
  throw new Error('Playwright not found: npm install playwright');
}

const { chromium } = loadPlaywright();
const jobs = JSON.parse(process.argv[2]);
const browser = await chromium.launch({ args: ['--allow-file-access-from-files'] });
for (const job of jobs) {
  const page = await browser.newPage();
  await page.goto('file://' + job.html, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(500);
  await page.pdf({
    path: job.pdf,
    width: job.width,
    height: job.height,
    printBackground: true,
    preferCSSPageSize: true,
    margin: { top: 0, right: 0, bottom: 0, left: 0 },
  });
  console.log(`pdf ${job.pdf} (${job.pages} pages expected)`);
  await page.close();
}
await browser.close();
