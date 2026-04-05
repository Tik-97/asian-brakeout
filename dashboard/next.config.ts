import path from "path";
import type { NextConfig } from "next";

const distDir = process.env.NEXT_BUILD_DIR || ".next";

const nextConfig: NextConfig = {
  distDir,
  output: "standalone",
  outputFileTracingRoot: path.join(process.cwd()),
};

export default nextConfig;
