import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const distDirName = process.env.NEXT_BUILD_DIR || ".next";
const publicDir = path.join(rootDir, "public");
const distDir = path.join(rootDir, distDirName);
const standaloneDir = path.join(distDir, "standalone");
const standalonePublicDir = path.join(standaloneDir, "public");
const staticDir = path.join(distDir, "static");
const standaloneStaticDir = path.join(standaloneDir, ".next", "static");

if (!existsSync(standaloneDir)) {
  console.warn(`No standalone directory found at ${standaloneDir}, skipping asset copy.`);
  process.exit(0);
}

if (!existsSync(publicDir)) {
  console.warn("No public directory found, skipping standalone asset copy.");
} else {
  rmSync(standalonePublicDir, { recursive: true, force: true });
  mkdirSync(path.dirname(standalonePublicDir), { recursive: true });
  cpSync(publicDir, standalonePublicDir, { recursive: true });
}

if (!existsSync(staticDir)) {
  console.warn(`No static directory found at ${staticDir}, skipping static asset copy.`);
} else {
  rmSync(standaloneStaticDir, { recursive: true, force: true });
  mkdirSync(path.dirname(standaloneStaticDir), { recursive: true });
  cpSync(staticDir, standaloneStaticDir, { recursive: true });
}

console.log(`Copied public assets to ${standalonePublicDir}`);
console.log(`Copied static assets to ${standaloneStaticDir}`);
