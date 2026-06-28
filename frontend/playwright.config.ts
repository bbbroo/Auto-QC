import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendDir, "..");
const e2eDataDir = path.join(repoRoot, "data", "e2e");
const e2eDbPath = path.join(e2eDataDir, "autoqc.sqlite");
const backendUrl = "http://127.0.0.1:8010";
const frontendUrl = "http://127.0.0.1:5180";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: frontendUrl,
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: "python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010",
      cwd: repoRoot,
      url: `${backendUrl}/health`,
      reuseExistingServer: process.env.PW_REUSE_SERVER === "1",
      timeout: 120_000,
      env: {
        AUTOQC_DATA_DIR: e2eDataDir,
        AUTOQC_DB_PATH: e2eDbPath,
      },
    },
    {
      command: "npm run dev:e2e",
      cwd: frontendDir,
      url: frontendUrl,
      reuseExistingServer: process.env.PW_REUSE_SERVER === "1",
      timeout: 60_000,
      env: {
        AUTOQC_API_PROXY_TARGET: backendUrl,
      },
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
