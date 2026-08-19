#!/usr/bin/env node
// Automated a11y audit: serves the static export and runs axe-core over the
// key routes. Requires a Playwright chromium browser:
//   npx playwright install chromium
// Skips gracefully (exit 0) if chromium is not installed.

import { createServer } from "http";
import { readFile, stat, readdir } from "fs/promises";
import { existsSync } from "fs";
import { homedir } from "os";
import { extname, join, normalize } from "path";
import { chromium } from "playwright";
import { AxeBuilder } from "@axe-core/playwright";

const OUT_DIR = new URL("../out/", import.meta.url).pathname;
const PORT = 3199;
const ROUTES = ["/", "/login/", "/admin/"];

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".json": "application/json",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".webmanifest": "application/manifest+json",
};

const server = createServer(async (req, res) => {
  try {
    let urlPath = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (urlPath.endsWith("/")) urlPath += "index.html";
    let filePath = normalize(join(OUT_DIR, urlPath));
    if (!filePath.startsWith(OUT_DIR)) throw new Error("bad path");
    const body = await readFile(filePath);
    res.writeHead(200, {
      "Content-Type": MIME[extname(filePath)] ?? "application/octet-stream",
    });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("not found");
  }
});

async function browserReady() {
  const cache = join(homedir(), "AppData", "Local", "ms-playwright");
  if (!existsSync(cache)) return false;
  try {
    return (await readdir(cache)).length > 0;
  } catch {
    return false;
  }
}

const run = async () => {
  const outExists = await stat(OUT_DIR).catch(() => null);
  if (!outExists) {
    console.error("Run `npm run build` first so that out/ exists.");
    process.exit(1);
  }
  if (!(await browserReady())) {
    console.warn(
      "Playwright chromium not installed; skipping axe audit.\n" +
        "  Run: npx playwright install chromium"
    );
    process.exit(0);
  }

  await new Promise((resolve) => server.listen(PORT, resolve));
  const browser = await chromium.launch();
  let failed = false;
  try {
    for (const route of ROUTES) {
      const page = await browser.newPage();
      await page.goto(`http://localhost:${PORT}${route}`, {
        waitUntil: "networkidle",
      });
      const results = await new AxeBuilder({ page }).analyze();
      await page.close();
      const violations = results.violations.filter(
        (v) => v.impact === "critical" || v.impact === "serious"
      );
      console.log(
        `\n[${route}] axe: ${results.violations.length} total, ${violations.length} critical/serious`
      );
      for (const v of violations) {
        console.log(`  ${v.impact.toUpperCase()} ${v.id}: ${v.help}`);
        for (const n of v.nodes.slice(0, 3)) {
          console.log(`    - ${n.target.join(" ")}`);
        }
      }
      if (violations.length > 0) failed = true;
    }
  } finally {
    await browser.close();
    server.close();
  }
  if (failed) process.exit(1);
  console.log("\naxe audit complete: no critical/serious violations.");
};

run().catch((err) => {
  console.error(err);
  process.exit(1);
});