import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const publicDir = path.join(rootDir, "public");
const standalonePublicDir = path.join(rootDir, ".next", "standalone", "public");

if (!existsSync(publicDir)) {
  console.warn("No public directory found, skipping standalone asset copy.");
  process.exit(0);
}

rmSync(standalonePublicDir, { recursive: true, force: true });
mkdirSync(path.dirname(standalonePublicDir), { recursive: true });
cpSync(publicDir, standalonePublicDir, { recursive: true });

console.log(`Copied public assets to ${standalonePublicDir}`);
