// Screenshot real Claude/Anthropic pages through the session proxy.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const PAGES = [
  { url: 'https://claude.com', name: 'claude-home' },
  { url: 'https://claude.com/product/claude-code', name: 'claude-code-page' },
  { url: 'https://www.anthropic.com', name: 'anthropic-home' },
  { url: 'https://code.claude.com/docs/en/overview', name: 'claude-docs' },
];

(async () => {
  const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    proxy: { server: process.env.HTTPS_PROXY },
    args: ['--no-sandbox'],
  });
  for (const { url, name } of PAGES) {
    const ctx = await browser.newContext({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 1.5,
      colorScheme: 'dark',
    });
    const page = await ctx.newPage();
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForTimeout(7000);
      await page.screenshot({ path: `assets/raw_${name}.png` });
      console.log('ok', name);
    } catch (e) {
      console.log('FAIL', name, e.message.split('\n')[0]);
    }
    await ctx.close();
  }
  await browser.close();
})();
