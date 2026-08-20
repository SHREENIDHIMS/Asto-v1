#!/usr/bin/env node
// Automated a11y audit: serves the static export and runs axe-core over the
// key routes. Requires a Playwright chromium browser:
//   npx playwright install chromium
// Fails (exit 1) if chromium is not installed so a CI gate cannot silently
// pass without actually auditing anything.

import { createServer } from "http";
import { readFileSync, statSync, existsSync } from "fs";
import { extname, join, normalize } from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";
import { AxeBuilder } from "@axe-core/playwright";

const OUT_DIR = fileURLToPath(new URL("../out/", import.meta.url));
const PORT = 3199;
// Every app route that a user lands on. Auth-gated pages render their
// loading/redirect shell when unauthenticated; axe still audits that DOM.
const ROUTES = ["/", "/login/", "/admin/", "/client/", "/staff/"];

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

// Synchronous handler: each request is served atomically. An async handler
// could interleave requests and emit duplicate/wrong bodies on the same
// response (ERR_HTTP_HEADERS_SENT). Mirrors the production nginx static
// host: a path that maps to a directory redirects (301) to the trailing-
// slash form before serving its index.html — without this, the app's own
// `/` -> `/login` redirect lands on a 404 body and axe flags
// document-title/html-has-lang spuriously.
const server = createServer((req, res) => {
  try {
    let urlPath = decodeURIComponent(new URL(req.url, "http://x").pathname);
    let filePath = normalize(join(OUT_DIR, urlPath));
    if (!filePath.startsWith(OUT_DIR)) throw new Error("bad path");
    if (statSync(filePath).isDirectory()) {
      if (!req.url.endsWith("/")) {
        res.writeHead(301, { Location: `${req.url}/` });
        res.end();
        return;
      }
      filePath = normalize(join(filePath, "index.html"));
    }
    const body = readFileSync(filePath);
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
  // Cross-platform: resolve the executable the installed Playwright browser
  // actually uses, rather than guessing at an OS-specific cache directory.
  try {
    return existsSync(chromium.executablePath());
  } catch {
    return false;
  }
}

const run = async () => {
  let outExists = false;
  try {
    outExists = statSync(OUT_DIR).isDirectory();
  } catch {
    outExists = false;
  }
  if (!outExists) {
    console.error("Run `npm run build` first so that out/ exists.");
    process.exit(1);
  }
  if (!(await browserReady())) {
    console.error(
      "Playwright chromium is not installed; the a11y audit would be a no-op.\n" +
        "  Run: npx playwright install chromium"
    );
    process.exit(1);
  }

  await new Promise((resolve) => server.listen(PORT, resolve));
  const browser = await chromium.launch();
  let failed = false;
  try {
    for (const route of ROUTES) {
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.goto(`http://localhost:${PORT}${route}`, {
        waitUntil: "networkidle",
      });
      const results = await new AxeBuilder({ page }).analyze();
      await context.close();
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