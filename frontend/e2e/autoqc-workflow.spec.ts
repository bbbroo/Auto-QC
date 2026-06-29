import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const apiBaseUrl = "http://127.0.0.1:8010";
const e2eDir = path.dirname(fileURLToPath(import.meta.url));
const validAiFixture = path.join(e2eDir, "fixtures", "valid-ai-updates.json");

async function clearProjects(request: APIRequestContext) {
  const response = await request.get(`${apiBaseUrl}/projects`);
  expect(response.ok()).toBeTruthy();
  const projects = (await response.json()) as Array<{ id: string }>;
  for (const project of projects) {
    await request.delete(`${apiBaseUrl}/projects/${project.id}`);
  }
}

async function openUploadSectionIfNeeded(page: Page) {
  const sampleButton = page.getByRole("button", { name: "Sample Package" });
  if (!(await sampleButton.isVisible())) {
    await page.getByText("Upload / sample package").click();
  }
}

async function createSampleAndImportValidAi(page: Page) {
  await openUploadSectionIfNeeded(page);
  await page.getByRole("button", { name: "Sample Package" }).click();
  await expect(page.getByText("Synthetic Regulator Station Sample").first()).toBeVisible();
  await page.getByRole("tab", { name: /Review/ }).click();
  await page.getByRole("button", { name: "Chat Prompt" }).click();
  const validAiJson = await fs.readFile(validAiFixture, "utf-8");
  await page.getByLabel("Paste AI update JSON").fill(validAiJson);
  await page.getByRole("button", { name: "Preview AI Updates" }).click();
  await expect(page.getByLabel("AI import preview")).toBeVisible();
  await page.getByRole("button", { name: "Import Valid Updates" }).click();
  await expect(page.getByText("Imported 2 AI updates.")).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  await clearProjects(request);
});

test("manual Chat Prompt AI workflow can preview, import, review, and export", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Go to review library" })).toBeVisible();
  await expect(page.getByText("No projects yet")).toBeVisible();
  await expect(page.getByText("No project selected").first()).toBeVisible();
  await page.getByRole("button", { name: "Open AutoQC help" }).click();
  await expect(page.getByRole("dialog", { name: "How to use AutoQC" })).toContainText("Attach the same PDF in ChatGPT or Copilot");
  await expect(page.getByRole("dialog", { name: "How to use AutoQC" })).toContainText("not engineering authority");
  await page.getByRole("button", { name: "Close help" }).click();

  await openUploadSectionIfNeeded(page);
  await page.getByRole("button", { name: "Sample Package" }).click();
  await expect(page.getByText("Synthetic Regulator Station Sample").first()).toBeVisible();
  await expect(page.getByText("5 sheets").first()).toBeVisible();

  await page.getByRole("tab", { name: /Projects/ }).click();
  await page.locator(".project-select-button", { hasText: "Synthetic Regulator Station Sample" }).click();

  await page.getByRole("tab", { name: /Sheets/ }).click();
  await expect(page.getByRole("button", { name: /PFD-100/ })).toBeVisible();
  await page.getByRole("button", { name: /PFD-100/ }).click();
  await expect(page.getByRole("heading", { name: /PFD-100/ })).toBeVisible();
  await expect(page.locator(".viewer-open-link[title*='source PDF']")).toBeVisible();

  await page.getByRole("tab", { name: /Review/ }).click();
  await expect(page.getByRole("combobox", { name: "Prompt template" })).toBeVisible();
  await expect(page.getByLabel("System Check panel")).toContainText("System Check");
  await expect(page.getByLabel("What should I do next")).toContainText("Upload PDF");
  await expect(page.getByLabel("Recovery Center")).toContainText(/No AI findings imported yet|No active recovery items/);
  await page.getByRole("button", { name: "Chat Prompt" }).click();
  await expect(page.getByText("Manual Bridge Pro")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Source PDF", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Copy Prompt|Prompt Copied/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download Prompt" })).toHaveAttribute("download", /autoqc-chat-prompt-/);

  const aiJsonInput = page.getByLabel("Paste AI update JSON");
  await aiJsonInput.fill('{"updates": [ { "page_number": 1, ');
  await page.getByRole("button", { name: "Preview AI Updates" }).click();
  await expect(page.getByRole("alert")).toContainText(/valid JSON|recoverable update data|could not be repaired/);
  await page.getByRole("button", { name: "Dismiss error" }).click();

  const validAiJson = await fs.readFile(validAiFixture, "utf-8");
  await aiJsonInput.fill(validAiJson);
  await page.getByRole("button", { name: "Preview AI Updates" }).click();
  const preview = page.getByLabel("AI import preview");
  await expect(preview).toBeVisible();
  await expect(preview).toContainText("2");
  await expect(preview).toContainText("valid");
  await expect(preview).toContainText("autoqc-ai-updates-v1");
  await expect(preview).toContainText("INLET ISOLATION VALVE V-101");

  await page.getByRole("button", { name: "Import Valid Updates" }).click();
  await expect(page.getByText("Imported 2 AI updates.")).toBeVisible();
  await expect(page.getByText("AI Import History")).toBeVisible();

  await page.getByRole("tab", { name: /Findings/ }).click();
  await expect(page.getByText("2 left to review")).toBeVisible();
  await expect(page.getByText("Auto-advance")).toBeVisible();
  await expect(page.getByText("A", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Located" }).click();
  await page.getByRole("button", { name: "All placement" }).click();
  const inletFinding = page.locator(".finding-item", { hasText: /Inlet isolation valve tag should be coordinated/ });
  const maopFinding = page.locator(".finding-item", { hasText: /MAOP and OPP setpoint confirmation note needs closure/ });
  await expect(inletFinding).toBeVisible();
  await expect(maopFinding).toBeVisible();

  const search = page.getByPlaceholder("Search findings");
  await search.fill("MAOP");
  await expect(maopFinding).toBeVisible();
  await expect(inletFinding).toBeHidden();
  await search.fill("no matching text");
  await expect(page.getByText("No findings match")).toBeVisible();
  await search.fill("");

  await inletFinding.click();
  await expect(page.getByRole("tab", { name: "Finding Focus" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("Inspector", { exact: true })).toBeVisible();
  await expect(page.locator(".viewer-finding-card")).toHaveCount(0);
  await expect(page.getByLabel("Manual markup placement")).toContainText(/Exact target found|Fuzzy target found|Page-level finding|Manual placement/);
  await expect(page.getByRole("button", { name: "Place on drawing" })).toBeVisible();
  await page.getByRole("button", { name: "Next sheet" }).click();
  await expect(page.getByRole("heading", { name: /PID-100/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Full Sheet" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Previous sheet" }).click();
  await expect(page.getByRole("heading", { name: /PFD-100/ })).toBeVisible();
  await page.getByRole("tab", { name: /Findings/ }).click();
  await inletFinding.click();
  await expect(page.getByText("Inspector", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /Findings/ }).click();
  await page.getByLabel("Auto-advance").uncheck();
  await page.getByRole("tab", { name: /Inspect/ }).click();
  await expect(page.getByText("Duplicate / merge")).toBeVisible();
  const titleInput = page.getByRole("textbox", { name: "Title" });
  await titleInput.fill("Reviewer edited inlet valve coordination");
  await page.getByLabel("Final PDF comment").fill("Reviewer final PDF comment for E2E export.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(titleInput).toHaveValue("Reviewer edited inlet valve coordination");

  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByLabel("Status")).toHaveValue("rejected");
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await expect(page.getByLabel("Status")).toHaveValue("needs_review");

  await page.getByRole("tab", { name: /Export/ }).click();
  await expect(page.getByRole("button", { name: "Draft", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Final", exact: true })).toBeVisible();
  await expect(page.getByText("0 findings selected for draft export.")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("No findings match the selected status filters");
  await expect(page.getByRole("button", { name: "Create Draft Export" })).toBeDisabled();
  await expect(page.getByText("Accepted").last()).toBeVisible();
  await expect(page.getByText("Needs Review").last()).toBeVisible();
  await expect(page.getByText("Rejected").last()).toBeVisible();

  await page.getByRole("tab", { name: /Inspect/ }).click();
  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByLabel("Status")).toHaveValue("accepted");

  await page.getByRole("tab", { name: /Export/ }).click();
  await expect(page.getByText("1 finding selected for draft export.")).toBeVisible();
  await page.getByRole("button", { name: "Create Draft Export" }).click();
  await expect(page.getByRole("link", { name: "Download Marked PDF" })).toBeVisible();
  await expect(page.getByText(/Validation (Passed|Warning|Failed)/)).toBeVisible();
  await expect(page.getByText("Generated files")).toBeVisible();
  await page.getByRole("tab", { name: /Review/ }).click();
  await expect(page.getByLabel("Full audit log")).toContainText(/Draft export created|AI updates imported/);
});

test("import history can remove an imported batch with confirmation", async ({ page }) => {
  await page.goto("/");
  await createSampleAndImportValidAi(page);

  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("2 findings");
    await dialog.accept();
  });
  await page.getByText("AI Import History").click();
  await page.getByRole("button", { name: "Remove imported batch" }).click();
  await expect(page.getByText(/Rolled back import batch and removed 2 findings/)).toBeVisible();
  await page.getByRole("tab", { name: /Findings/ }).click();
  await expect(page.getByText("No AI findings imported yet")).toBeVisible();
  await page.getByRole("tab", { name: /Review/ }).click();
  await expect(page.getByLabel("Full audit log")).toContainText("AI import batch rolled back");
});

test("PDF viewer supports pane zoom, markup selection, no popup, and left rail collapse", async ({ page }) => {
  await page.goto("/");
  await createSampleAndImportValidAi(page);
  await page.getByRole("tab", { name: /Sheets/ }).click();
  await page.getByRole("button", { name: /PFD-100/ }).click();

  const viewport = page.locator(".drawing-pan-viewport");
  const stage = page.locator(".drawing-stage");
  await expect(viewport).toBeVisible();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();

  const scrollResult = await viewport.evaluate((node) => {
    const element = node as HTMLElement;
    const canScroll = element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight;
    element.scrollLeft = 40;
    element.scrollTop = 40;
    return { canScroll, left: element.scrollLeft, top: element.scrollTop };
  });
  expect(scrollResult.canScroll).toBeTruthy();
  expect(scrollResult.left + scrollResult.top).toBeGreaterThan(0);

  const beforeZoom = await stage.boundingBox();
  const beforeWindowScroll = await page.evaluate(() => window.scrollY);
  await viewport.dispatchEvent("wheel", {
    deltaY: -180,
    clientX: 240,
    clientY: 220,
    ctrlKey: true,
  });
  await page.waitForTimeout(80);
  const afterZoom = await stage.boundingBox();
  const afterWindowScroll = await page.evaluate(() => window.scrollY);
  expect(afterZoom?.width ?? 0).toBeGreaterThan(beforeZoom?.width ?? 0);
  expect(afterWindowScroll).toBe(beforeWindowScroll);

  await page.locator(".finding-overlay").first().click();
  await expect(page.getByText("Inspector", { exact: true })).toBeVisible();
  await expect(page.locator(".viewer-finding-card")).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Finding Focus" })).toHaveAttribute("aria-selected", "true");

  const beforeCollapse = await page.locator(".viewer-pane").boundingBox();
  await page.getByRole("button", { name: "Collapse left panel" }).click();
  const afterCollapse = await page.locator(".viewer-pane").boundingBox();
  expect(afterCollapse?.width ?? 0).toBeGreaterThan(beforeCollapse?.width ?? 0);
});

test("backend unavailable state shows a visible alert", async ({ page }) => {
  await page.route("**/api/projects", (route) => route.abort());

  await page.goto("/");

  await expect(page.getByRole("alert")).toContainText(/Failed to fetch|Load failed|NetworkError/);
});

test("narrow viewport keeps the workflow reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 820 });
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Go to review library" })).toBeVisible();
  await openUploadSectionIfNeeded(page);
  await page.getByRole("button", { name: "Sample Package" }).click();
  await expect(page.getByText("Synthetic Regulator Station Sample").first()).toBeVisible();
  await expect(page.getByRole("tab", { name: /Sheets/ }).first()).toBeVisible();

  const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(horizontalOverflow).toBeLessThanOrEqual(2);
});

test("keyboard focus is visible and can move through primary controls", async ({ page }) => {
  await page.goto("/");

  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press("Tab");
    const activeTag = await page.evaluate(() => document.activeElement?.tagName ?? "");
    expect(activeTag).not.toBe("BODY");
    await expect(page.locator(":focus")).toBeVisible();
  }

  const hasVisibleFocus = await page.evaluate(() => Boolean(document.activeElement?.matches(":focus-visible")));
  expect(hasVisibleFocus).toBeTruthy();

  await page.getByRole("tab", { name: "Projects" }).focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("tab", { name: "Sheets" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Export" })).toHaveAttribute("aria-selected", "true");
});
