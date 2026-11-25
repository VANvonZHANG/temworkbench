import { fileURLToPath } from "node:url"
import { defineConfig } from "@playwright/test"

const externalUrl = process.env.TEMWORKBENCH_TEST_URL
const baseURL = externalUrl ?? "http://127.0.0.1:18765"

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 45_000,
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: externalUrl ? undefined : {
    command: "uv run --locked python frontend/tests/serve.py",
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    url: baseURL,
    timeout: 30_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
})
