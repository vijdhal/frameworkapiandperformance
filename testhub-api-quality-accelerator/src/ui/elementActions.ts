/**
 * TestHub UI Engine — Element Actions (keyword layer)
 *
 * ⚠ See the alignment note at the top of browserActions.ts. This file is
 * TestHub-Studio-owned scaffolding for the generic Web UI engine.
 *
 * PROVENANCE CORRECTED 2026-08-15. This note previously said the accelerator had
 * "deleted its ElementUtil.ts in 44b01f9 and moved to page objects", and used
 * that to justify a separate layer. True when written, wrong now: the accelerator
 * REVERSED that in 7a13c8e ("Extract generic element actions into
 * ElementUtilActions") and its generic layer is back as
 * src/utils/elementUtilActions.ts — 31 methods covering the same surface.
 *
 * So two generic element layers now exist for one job. The accelerator's is the
 * one that should survive: they own the framework tier. Treat this file as the
 * Studio's temporary shim until the naming differences are settled upstream
 * (see samples/keyword-catalogue.json), not as a parallel design.
 *
 * Contract rule still holds: generated specs call these keywords only, so the
 * implementation can be replaced without touching a single generated test.
 *
 * Every keyword takes a *locator string* rather than a Playwright Locator, so
 * the Studio can emit them from a plain step table and a non-coder can read
 * the resulting spec.
 */

import { expect, Locator } from '@playwright/test';
import { getActiveFrame, getActivePage } from './browserExtensions';

/** Default per-keyword wait. Overridable per call for slow enterprise apps. */
export const DEFAULT_TIMEOUT = 15_000;

/**
 * Resolve a locator string. Supports the forms a tester will actually type:
 *   "#id"  ".class"  "//xpath"  "css=…"  "text=…"  "role=button[name=Save]"
 * Anything starting with "//" or "(" is treated as XPath, matching Selenium
 * and Robot habits — that is the muscle memory this layer has to respect.
 */
export function resolve(locator: string): Locator {
  // Resolves through the extension layer, not the page directly, so that
  // `selectFrame` and `switchWindow` actually scope every keyword below without
  // each one having to know they exist. With no frame or tab selected this is
  // the vendored session's own page, exactly as before.
  const root = getActiveFrame() ?? getActivePage();
  const l = locator.trim();
  if (l.startsWith('//') || l.startsWith('(')) return root.locator(`xpath=${l}`);
  return root.locator(l);
}

export async function click(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).click({ timeout });
}

export async function doubleClick(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).dblclick({ timeout });
}

export async function fill(locator: string, value: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).fill(value, { timeout });
}

/** Clears then types character by character — for fields with keystroke handlers. */
export async function type(locator: string, value: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  const el = resolve(locator);
  await el.click({ timeout });
  await el.fill('', { timeout });
  await el.pressSequentially(value, { delay: 20 });
}

export async function clear(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).fill('', { timeout });
}

export async function check(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).check({ timeout });
}

export async function uncheck(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).uncheck({ timeout });
}

export async function selectOption(locator: string, value: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).selectOption(value, { timeout });
}

export async function hover(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).hover({ timeout });
}

export async function pressKey(key: string): Promise<void> {
  await getActivePage().keyboard.press(key);
}

/**
 * Selects a radio button. Separate from `check` on purpose: the vocabulary the
 * team is targeting distinguishes "Select Checkbox" from "Select Radio Button",
 * and a tester reading a step table should see the control they are looking at.
 * A radio cannot be unselected — there is deliberately no `unselectRadio`.
 */
export async function selectRadio(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).check({ timeout });
}

/**
 * Waits until `text` appears anywhere on the page.
 *
 * Scoped to the first match and to visible text, so it means what a tester
 * expects — "I can see it" — rather than passing on a string buried in a hidden
 * node or a script tag, which is how this keyword usually goes wrong.
 */
export async function waitForPageContains(text: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  // Filter to visible BEFORE taking .first(). Pinning .first() and then waiting
  // for it to become visible times out whenever an earlier match is hidden — a
  // template, a collapsed panel — even though the text is plainly on screen.
  const root = getActiveFrame() ?? getActivePage();
  await root.getByText(text, { exact: false })
    .filter({ visible: true })
    .first()
    .waitFor({ state: 'visible', timeout });
}

export async function uploadFile(locator: string, filePath: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).setInputFiles(filePath, { timeout });
}

export async function getText(locator: string, timeout = DEFAULT_TIMEOUT): Promise<string> {
  return (await resolve(locator).textContent({ timeout })) ?? '';
}

export async function getValue(locator: string, timeout = DEFAULT_TIMEOUT): Promise<string> {
  return resolve(locator).inputValue({ timeout });
}

export async function isVisible(locator: string): Promise<boolean> {
  return resolve(locator).isVisible();
}

export async function waitForVisible(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).waitFor({ state: 'visible', timeout });
}

export async function waitForHidden(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await resolve(locator).waitFor({ state: 'hidden', timeout });
}

// ───────────────────────── assertions ─────────────────────────
// Kept in the same layer so a generated spec has exactly two imports.

export async function expectVisible(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await expect(resolve(locator)).toBeVisible({ timeout });
}

export async function expectHidden(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await expect(resolve(locator)).toBeHidden({ timeout });
}

export async function expectText(locator: string, expected: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await expect(resolve(locator)).toContainText(expected, { timeout });
}

export async function expectValue(locator: string, expected: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await expect(resolve(locator)).toHaveValue(expected, { timeout });
}

export async function expectEnabled(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await expect(resolve(locator)).toBeEnabled({ timeout });
}

export async function expectDisabled(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  await expect(resolve(locator)).toBeDisabled({ timeout });
}

export async function expectTitle(expected: string): Promise<void> {
  await expect(getActivePage()).toHaveTitle(new RegExp(escapeRegExp(expected)));
}

export async function expectUrlContains(fragment: string): Promise<void> {
  await expect(getActivePage()).toHaveURL(new RegExp(escapeRegExp(fragment)));
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
