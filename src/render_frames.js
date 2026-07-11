// Deterministic frame renderer: load build/video.html in chromium, step t frame by frame,
// pipe JPEG screenshots straight into ffmpeg (no frames on disk).
// Usage: node src/render_frames.js [--preview t1,t2,...]  (preview writes PNGs instead)
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const { spawn } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const FPS = 24;
const analysis = require(path.join(ROOT, 'analysis.json'));
const DUR = analysis.duration_sec;

(async () => {
  const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    args: ['--no-sandbox', '--force-device-scale-factor=1', '--hide-scrollbars'],
  });
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  await page.goto('file://' + path.join(ROOT, 'build', 'video.html'));
  await page.waitForTimeout(1500);

  const previewIdx = process.argv.indexOf('--preview');
  if (previewIdx !== -1) {
    const times = process.argv[previewIdx + 1].split(',').map(Number);
    for (const t of times) {
      await page.evaluate((tt) => window.renderAt(tt), t);
      await page.screenshot({ path: path.join(ROOT, 'build', `preview_${t.toFixed(1)}.png`) });
      console.log('preview', t);
    }
    // cover / thumbnail
    await page.evaluate(() => window.renderCover());
    await page.screenshot({ path: path.join(ROOT, 'assets', 'cover.png') });
    console.log('cover written');
    await browser.close();
    return;
  }

  const total = Math.ceil(DUR * FPS);
  const ff = spawn('ffmpeg', [
    '-y', '-v', 'error',
    '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
    path.join(ROOT, 'build', 'video_noaudio.mp4'),
  ], { stdio: ['pipe', 'inherit', 'inherit'] });

  const t0 = Date.now();
  for (let i = 0; i < total; i++) {
    const t = i / FPS;
    await page.evaluate((tt) => window.renderAt(tt), t);
    const buf = await page.screenshot({ type: 'jpeg', quality: 90 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
    if (i % 240 === 0) {
      const el = (Date.now() - t0) / 1000;
      console.log(`frame ${i}/${total} (${(i / total * 100).toFixed(1)}%) ${(i / el).toFixed(1)} fps`);
    }
  }
  ff.stdin.end();
  await new Promise((r) => ff.on('close', r));
  await browser.close();
  console.log('video_noaudio.mp4 done in', ((Date.now() - t0) / 60000).toFixed(1), 'min');
})();
