import { randomUUID } from "node:crypto"
import { readFile } from "node:fs/promises"
import { expect, test } from "@playwright/test"

const operator = "browser-test-operator"
const agent = "browser-test-agent"

test("theme persists and operator access is required", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Connect to the simulator" })).toBeVisible()
  await expect(page.locator("html")).toHaveClass("dark")
  await page.getByRole("button", { name: "Use light theme" }).click()
  await page.reload()
  await expect(page.locator("html")).not.toHaveClass("dark")
  const session = page.getByLabel("Session ID")
  await session.fill("Invalid session")
  expect(await session.evaluate((field: HTMLInputElement) => field.validity.patternMismatch)).toBe(true)
  await session.fill("test-operator")
  await page.getByLabel("Operator token").fill(agent)
  await page.getByRole("button", { name: "Connect", exact: true }).click()
  await expect(page.getByRole("alert")).toHaveText("Operator token required")
  await expect(page.getByRole("button", { name: "Stop and blank beam" })).toHaveCount(0)
})

test("preview disconnection is visible before the first frame", async ({ page }) => {
  await page.routeWebSocket("**/api/preview", (socket) => {
    socket.close({ code: 1011 })
  })
  await page.goto("/")
  await page.getByLabel("Operator token").fill(operator)
  await page.getByRole("button", { name: "Connect", exact: true }).click()
  await page.getByRole("button", { name: "Start preview" }).click()
  const camera = page.getByRole("region", { name: "Camera preview" })
  await expect(camera.getByText("Disconnected", { exact: true })).toBeVisible()
  await expect(camera.getByText("No camera frame received.")).toBeVisible({ timeout: 2000 })
  await expect(camera.getByRole("button", { name: "Start preview" })).toBeEnabled()
})

test("operate the simulator through the compiled console", async ({ page, request }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  let previewRequests = 0
  page.on("websocket", (socket) => {
    if (socket.url().endsWith("/api/preview")) {
      socket.on("framesent", (frame) => {
        if (typeof frame.payload === "string" && frame.payload.includes("exposure_s")) previewRequests++
      })
    }
  })

  await page.goto("/")
  await page.getByLabel("Operator token").fill(operator)
  await page.getByLabel("Session ID").fill("browser-session")
  await page.getByRole("button", { name: "Connect", exact: true }).click()
  await expect(page.getByText("Simulator online")).toBeVisible()
  await expect(page.getByText("browser-session", { exact: true })).toBeVisible()
  const viewfinder = page.getByRole("figure", { name: "Simulator camera preview" })
  const background = await viewfinder.evaluate((element) => getComputedStyle(element).backgroundColor)
  await page.getByRole("button", { name: "Use light theme" }).click()
  await expect(viewfinder).toHaveCSS("background-color", background)
  await page.getByRole("button", { name: "Use dark theme" }).click()

  await page.getByLabel("Exposure (s)").fill("1.2")
  await page.getByLabel("Binning").selectOption("4")
  await page.getByLabel("Acquisition note").fill("Browser acceptance")
  await page.getByRole("button", { name: "Start preview" }).click()
  const camera = page.getByRole("region", { name: "Camera preview" })
  const image = camera.getByRole("img", { name: "Simulated TEM camera frame" })
  await expect(camera.getByText("Live", { exact: true })).toBeVisible()
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0)
  await page.getByRole("button", { name: "Pause preview" }).click()
  const pausedFrame = await image.getAttribute("src")
  await expect(camera.getByText("Paused", { exact: true })).toBeVisible()
  await expect(image).toHaveAttribute("src", pausedFrame ?? "")
  await page.getByRole("button", { name: "Start preview" }).click()
  await expect(camera.getByText("Live", { exact: true })).toBeVisible()

  await page.getByRole("button", { name: "Acquire and save" }).click()
  await expect(camera.getByText("Acquiring", { exact: true })).toBeVisible()
  const duringCapture = previewRequests
  await expect(camera.getByText("Acquiring and saving…")).toBeVisible()
  expect(previewRequests).toBe(duringCapture)
  await expect(camera.getByText("Acquisition saved.")).toBeVisible()
  await expect(camera.getByText("Live", { exact: true })).toBeVisible()
  for (const format of ["HSPY", "TIFF"]) {
    const download = page.waitForEvent("download")
    await camera.getByRole("button", { name: `Download ${format}` }).click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(new RegExp(`^[a-f0-9-]+\\.${format.toLowerCase()}$`))
    const bytes = await readFile(await file.path())
    const expected = format === "HSPY" ? "894844460d0a1a0a" : "49492a00"
    expect(bytes.subarray(0, expected.length / 2).toString("hex")).toBe(expected)
  }

  async function requestAdjustment(command: Record<string, string | number>) {
    const command_id = randomUUID()
    const session_id = "agent-session"
    const response = await request.post("/api/commands", {
      headers: { Authorization: `Bearer ${agent}` },
      data: { command, command_id, session_id },
    })
    expect(response.ok()).toBe(true)
    expect(await response.json()).toMatchObject({ status: "pending_approval" })
    return `/api/jobs/${session_id}/${command_id}`
  }

  const brightnessJob = await requestAdjustment({ kind: "set_brightness", value: 23456 })
  const stageJob = await requestAdjustment({ kind: "move_stage", x_nm: 1234, y_nm: -5678 })
  const stage = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Move stage" }) })
  const brightness = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Set brightness" }) })
  await expect(stage.getByRole("cell", { name: "1234 nm", exact: true })).toBeVisible()
  await expect(stage.getByRole("cell", { name: "-5678 nm", exact: true })).toBeVisible()
  await expect(stage.getByText("Session agent-session")).toBeVisible()
  const approve = stage.getByRole("button", { name: "Approve" })
  await approve.focus()
  await page.waitForResponse((response) => new URL(response.url()).pathname === "/api/operator/approvals"
    && response.request().method() === "GET")
  await expect(approve).toBeFocused()
  await approve.press("Enter")
  await expect(stage).toHaveCount(0)
  await expect(brightness.getByRole("button", { name: "Approve" })).toBeFocused()
  await expect.poll(async () => {
    const response = await request.get(stageJob, { headers: { Authorization: `Bearer ${operator}` } })
    return (await response.json()).status
  }).toBe("succeeded")

  await page.setViewportSize({ width: 390, height: 844 })
  const stop = page.getByRole("button", { name: "Stop and blank beam" })
  await page.getByRole("link", { name: "1 pending" }).click()
  await expect(page.getByRole("heading", { name: "Operator approvals" })).toBeFocused()
  await expect(stop).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)

  const reject = brightness.getByRole("button", { name: "Reject" })
  await reject.focus()
  await reject.press("Enter")
  await expect(brightness).toHaveCount(0)
  await expect(page.getByRole("heading", { name: "Operator approvals" })).toBeFocused()
  const rejected = await request.get(brightnessJob, { headers: { Authorization: `Bearer ${operator}` } })
  expect(await rejected.json()).toMatchObject({ status: "rejected", error: "Operator denied the command" })

  await stop.click()
  await expect(page.getByText("Stopped. Beam blanked. Restart the service to resume acquisition.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Acquire and save" })).toBeDisabled()
  await expect(page.getByRole("button", { name: "Start preview" })).toBeDisabled()
  await page.getByRole("button", { name: "Disconnect" }).click()
  await expect(page.getByLabel("Operator token")).toBeFocused()
  await expect(page.getByLabel("Operator token")).toBeEmpty()
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual(["temworkbench-theme"])
  expect(errors).toEqual([])
})
