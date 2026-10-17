// Builds src/main.jsx into ../assets/hero3d.js and src/glass.js into
// ../assets/glass.js (self-hosted ES modules, loaded on demand by the page).
//   npm install && npm run build
// Fails if the bundle contains anything dunous.com's CSP would block
// (no 'unsafe-eval', no blob: workers) or grows past the size budget.
import { build } from "esbuild";
import { gzipSync } from "node:zlib";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = (rel) => fileURLToPath(new URL(rel, import.meta.url));

const outdir = here("../assets");
const BUDGET_GZ = 345 * 1024;   // three.js is most of it; R3F needs the whole namespace

const result = await build({
  entryPoints: [{ in: here("./src/main.jsx"), out: "hero3d" }, { in: here("./src/glass.js"), out: "glass" }],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020", "safari15"],
  jsx: "automatic",
  outdir,
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "none",
  metafile: true,
  logLevel: "warning",
});

writeFileSync(here("./meta.json"), JSON.stringify(result.metafile));
// blob: is fine for images (img-src allows it); only blob: scripts/workers and eval are blocked.
const banned = [/new Function\s*\(/, /\beval\s*\(/, /new (Shared)?Worker\s*\(/, /importScripts\s*\(/];
let failed = false;
for (const name of ["hero3d.js", "glass.js"]) {
  const file = `${outdir}/${name}`, code = readFileSync(file, "utf8");
  const hits = banned.filter((re) => re.test(code)).map(String);
  const gz = gzipSync(code).length;
  console.log(`${hits.length ? "✗" : "✓"} ${name}: ${(code.length / 1024).toFixed(0)} KB minified, ${(gz / 1024).toFixed(0)} KB gzipped`);
  if (hits.length) { console.error("  CSP-unsafe code:", hits.join(", ")); failed = true; }
  if (name === "hero3d.js" && gz > BUDGET_GZ) { console.error(`  over the ${BUDGET_GZ / 1024} KB budget`); failed = true; }
}
if (failed) process.exit(1);
