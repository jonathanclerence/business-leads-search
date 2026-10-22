// Prints the client PDFs for the Python tracker, which has no browser on Vercel
// (pipeline/documents.py → _remote). Takes the desktop and phone screenshots of
// the finished site first, drops them into the document, then prints it.
import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";

// The finished site is served from memory under this made-up origin, so its
// icon sprite loads (browsers refuse <use> across origins). Its shared assets
// come from the live dunous.com (/previewsite-assets/).
const BASE = "https://preview.dunous.test";
const BLANK = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
const SHOTS = [
  { key: "desktop", viewport: { width: 1280, height: 800, deviceScaleFactor: 1.5, isMobile: false, hasTouch: false } },
  { key: "phone", viewport: { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
];

export default async function handler(req, res) {
  const token = process.env.INTERNAL_TOKEN;
  if (req.method !== "POST" || !token || req.headers["x-internal-token"] !== token) {
    return res.status(403).json({ error: "forbidden" });
  }
  const { html, measure, site, assets_origin: origin } = req.body || {};
  if (!html || !measure) return res.status(400).json({ error: "html and measure are required" });

  // CHROME_PATH: a local Chrome, for trying this out on a Mac.
  const browser = await puppeteer.launch(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH, headless: true }
    : {
        args: await puppeteer.defaultArgs({ args: chromium.args, headless: "shell" }),
        executablePath: await chromium.executablePath(),
        headless: "shell",
      });
  try {
    let doc = html;
    if (site) {
      for (const { key, viewport } of SHOTS) {
        let shot = BLANK;
        try {
          shot = await screenshot(browser, site, origin, viewport);
        } catch (err) {
          console.error(`screenshot (${key}) failed:`, err);
        }
        doc = doc.replaceAll(`__SHOT_${key}__`, shot);
      }
    }
    const page = await browser.newPage();
    await page.setViewport({ width: 794, height: 1123 });
    await page.emulateMediaType("print");
    await page.setContent(doc, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    const measured = await page.evaluate(`(${measure})()`);
    const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true, tagged: true, outline: true });
    return res.status(200).json({ pdf: Buffer.from(pdf).toString("base64"), ...measured });
  } finally {
    await browser.close();
  }
}

async function screenshot(browser, site, origin, viewport) {
  const page = await browser.newPage();
  try {
    await page.setViewport(viewport);
    await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
    await page.setRequestInterception(true);
    page.on("request", async (request) => {
      const url = new URL(request.url());
      if (url.origin !== BASE) return request.abort();
      if (url.pathname === "/") {
        return request.respond({ status: 200, contentType: "text/html; charset=utf-8", body: site });
      }
      if (!url.pathname.startsWith("/previewsite-assets/")) return request.abort();
      try {
        const r = await fetch(origin + url.pathname);
        if (!r.ok) return request.abort();
        return request.respond({
          status: 200,
          contentType: r.headers.get("content-type") || "application/octet-stream",
          body: Buffer.from(await r.arrayBuffer()),
        });
      } catch {
        return request.abort();
      }
    });
    await page.goto(`${BASE}/`, { waitUntil: "load", timeout: 20000 });
    await page.evaluate(() => document.fonts.ready);
    await new Promise((r) => setTimeout(r, 300));
    // Stop above the scrolling strip under the hero, which a still frame cuts mid-word.
    const strip = await page.evaluate(() => document.querySelector(".marquee")?.getBoundingClientRect().top || 0);
    const height = strip > viewport.height * 0.6 ? Math.floor(Math.min(viewport.height, strip - 1)) : viewport.height;
    const shot = await page.screenshot({ type: "jpeg", quality: 78, clip: { x: 0, y: 0, width: viewport.width, height } });
    return `data:image/jpeg;base64,${Buffer.from(shot).toString("base64")}`;
  } finally {
    await page.close();
  }
}
