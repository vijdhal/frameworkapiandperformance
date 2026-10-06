/**
 * TestHub UI Engine — Browser Extensions (keyword layer, tier 1 primitives)
 *
 * The eleven primitives the team's Playwright_ReusableFunctions vocabulary needs
 * and neither implementation had: history navigation, tab/window switching,
 * frames, alerts and script execution.
 *
 * WHY A SEPARATE FILE. `browserActions.ts` is vendored verbatim from the
 * team's internal accelerator and says plainly at the top: do not fork the
 * behaviour here, changes belong
 * upstream. So nothing in this file edits it. These compose on top instead,
 * which keeps that copy refreshable and makes this work a clean, reviewable
 * proposal to upstream rather than a divergence someone has to untangle later.
 *
 * KNOWN SEAM, and it is the reason these belong upstream eventually. The
 * vendored `BrowserActions` keeps its "current page" private, so this layer
 * cannot repoint it. After `switchWindow`/`openNewTab`, the element keywords
 * follow the switched tab (they resolve through `getActivePage()` below), but
 * the vendored browser keywords — `goToURL`, `refreshPage`, `getTitle` — keep
 * acting on the session's own page. Documented rather than hidden: moving
 * `switchWindow` into `BrowserActions` upstream removes the split entirely.
 */

import { Dialog, FrameLocator, Page } from 'playwright';
import { getPage } from './browserActions';
import { createLogger } from './Logger';

const logger = createLogger('BrowserExtensions');

/** Default wait for keywords that block on a browser event. */
export const DEFAULT_TIMEOUT = 15_000;

// The active tab, when it differs from the vendored session's own page, and the
// frame that element lookups are scoped to. Module-level to match the singleton
// model the vendored layer and Robot Framework both use: keywords act on an
// implicit "current" target rather than an explicitly threaded handle.
let activePage: Page | null = null;
let activeFrame: FrameLocator | null = null;
// The page a frame was selected against. A FrameLocator does not expose its own
// page, so without this the frame outlives the tab it belongs to: activePage
// detects the closed page and falls back, while every element lookup keeps
// resolving into a dead frame and fails as a missing element rather than a
// stale context.
let activeFramePage: Page | null = null;

/**
 * The page element keywords should resolve against — the switched tab if there
 * is one, otherwise whatever the vendored session considers current.
 */
export function getActivePage(): Page {
  if (activePage && !activePage.isClosed()) return activePage;
  activePage = null;
  return getPage();
}

/** The frame element lookups are scoped to, or null for the top document. */
export function getActiveFrame(): FrameLocator | null {
  if (activeFrame && activeFramePage && activeFramePage.isClosed()) {
    activeFrame = null;
    activeFramePage = null;
  }
  return activeFrame;
}

/** Drop any tab/frame scoping. Call between tests — this state outlives one. */
export function resetContext(): void {
  activePage = null;
  activeFrame = null;
  activeFramePage = null;
}

// ─── History ─────────────────────────────────────────────────────────────────

export async function navigateBack(): Promise<void> {
  const page = getActivePage();
  logger.info(`navigateBack → from ${page.url()}`);
  await page.goBack();
}

export async function navigateForward(): Promise<void> {
  const page = getActivePage();
  logger.info(`navigateForward → from ${page.url()}`);
  await page.goForward();
}

// ─── Tabs and windows ────────────────────────────────────────────────────────

/**
 * Opens a new tab in the current browser context and switches to it. With a
 * `url` the tab is navigated before returning, so the caller never has to
 * decide whether the page is ready.
 *
 * Selecting a frame is meaningless in a tab you have just left, so the frame
 * scope is cleared here and on every other switch below.
 */
export async function openNewTab(url?: string): Promise<Page> {
  const context = getActivePage().context();
  const page = await context.newPage();
  if (url) await page.goto(url);
  activePage = page;
  activeFrame = null;
  activeFramePage = null;
  logger.info(`openNewTab → ${url ?? 'about:blank'} (${context.pages().length} tabs open)`);
  return page;
}

/**
 * Switches the active tab. Accepts what a tester will actually reach for:
 *
 *   switchWindow(1)                  // zero-based index
 *   switchWindow('title=Accounts')   // substring of the tab title
 *   switchWindow('url=/accounts')    // substring of the URL
 *   switchWindow('Accounts')         // bare string: title first, then URL
 *
 * Throws listing the open tabs when nothing matches. A silent no-op here is
 * how a suite ends up asserting confidently against the wrong tab.
 */
export async function switchWindow(target: number | string): Promise<Page> {
  const pages = getActivePage().context().pages();

  if (typeof target === 'number') {
    const page = pages[target];
    if (!page) {
      throw new Error(`switchWindow: no tab at index ${target} (${pages.length} open).`);
    }
    return activate(page, `index ${target}`);
  }

  const raw = target.trim();
  const byTitle = raw.startsWith('title=');
  const byUrl = raw.startsWith('url=');
  const needle = (byTitle || byUrl ? raw.slice(raw.indexOf('=') + 1) : raw).toLowerCase();

  const described: string[] = [];
  for (const page of pages) {
    const title = (await page.title().catch(() => '')).toLowerCase();
    const url = page.url().toLowerCase();
    described.push(`${await page.title().catch(() => '?')} — ${page.url()}`);
    const hit = byTitle ? title.includes(needle)
      : byUrl ? url.includes(needle)
        : title.includes(needle) || url.includes(needle);
    if (hit) return activate(page, raw);
  }

  throw new Error(
    `switchWindow: no tab matched "${target}". Open tabs:\n  ${described.join('\n  ')}`
  );
}

/**
 * Closes a tab — the active one by default, or one selected the same way
 * `switchWindow` selects. After closing, the most recently opened remaining tab
 * becomes active, mirroring the browser's own behaviour.
 */
export async function closeTab(target?: number | string): Promise<void> {
  const page = target === undefined ? getActivePage() : await switchWindow(target);
  const context = page.context();
  logger.info(`closeTab → ${page.url()}`);
  await page.close();

  const remaining = context.pages().filter((p) => !p.isClosed());
  activePage = remaining[remaining.length - 1] ?? null;
  activeFrame = null;
  activeFramePage = null;
}

async function activate(page: Page, how: string): Promise<Page> {
  await page.bringToFront().catch(() => {});   // no-op when headless
  activePage = page;
  activeFrame = null;
  activeFramePage = null;
  logger.info(`switchWindow → matched ${how}: ${page.url()}`);
  return page;
}

// ─── Frames ──────────────────────────────────────────────────────────────────

/**
 * Scopes subsequent element keywords to a frame. Element lookups resolve
 * through `getActiveFrame()`, so `selectFrame` then `click` behaves the way it
 * does in Robot Framework — the frame is implicit state, not a parameter every
 * keyword has to carry.
 *
 * Verifies the frame actually resolves rather than deferring the failure to the
 * first element lookup inside it, where the error would name the element and
 * send whoever reads it hunting for the wrong problem.
 */
export async function selectFrame(locator: string, timeout = DEFAULT_TIMEOUT): Promise<void> {
  const page = getActivePage();
  // Resolve from the frame already selected, when there is one, so selectFrame can
  // descend into a nested iframe. Resolving from the page every time made the
  // second call scope to the top document instead of inside the first frame.
  const root = getActiveFrame() ?? page;
  const l = locator.trim();
  const frame = l.startsWith('//') || l.startsWith('(')
    ? root.frameLocator(`xpath=${l}`)
    : root.frameLocator(l);

  await frame.locator(':root').waitFor({ state: 'attached', timeout }).catch(() => {
    throw new Error(`selectFrame: no frame matched "${locator}" within ${timeout}ms.`);
  });

  activeFrame = frame;
  activeFramePage = page;
  logger.info(`selectFrame → ${locator}`);
}

/** Returns element lookups to the top-level document. */
export function unselectFrame(): void {
  if (activeFrame) logger.info('unselectFrame → back to top document');
  activeFrame = null;
  activeFramePage = null;
}

// ─── Dialogs ─────────────────────────────────────────────────────────────────

/**
 * Waits for the next alert/confirm/prompt, acts on it, and returns its message
 * so a test can assert what the user was actually told.
 *
 * Playwright auto-dismisses dialogs when nothing is listening, which quietly
 * turns "the app warned the user" into a passing test. Attaching a one-shot
 * listener is what makes the dialog observable at all — so this keyword must be
 * armed BEFORE the click that triggers it:
 *
 *   const [message] = await Promise.all([handleAlert('accept'), click('#delete')]);
 */
export async function handleAlert(
  action: 'accept' | 'dismiss' = 'accept',
  promptText?: string,
  timeout = DEFAULT_TIMEOUT
): Promise<string> {
  const page = getActivePage();

  return new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => {
      page.off('dialog', onDialog);
      reject(new Error(`handleAlert: no dialog appeared within ${timeout}ms.`));
    }, timeout);

    const onDialog = (dialog: Dialog) => {
      clearTimeout(timer);
      const message = dialog.message();
      logger.info(`handleAlert → ${dialog.type()} "${message}" (${action})`);
      const settled = action === 'accept' ? dialog.accept(promptText) : dialog.dismiss();
      settled.then(() => resolve(message)).catch(reject);
    };

    page.once('dialog', onDialog);
  });
}

// ─── Script ──────────────────────────────────────────────────────────────────

/**
 * Runs JavaScript in the page and returns its result.
 *
 * Deliberately last in this file and worth saying out loud: every use is a
 * place the test stops going through the interface the user goes through. It
 * earns its keep for setup and teardown a UI cannot reach; reaching for it to
 * make a flaky assertion pass converts a real defect into a green run.
 */
export async function executeJavaScript<T = unknown>(script: string, arg?: unknown): Promise<T> {
  const page = getActivePage();
  logger.info(`executeJavaScript → ${script.slice(0, 80)}${script.length > 80 ? '…' : ''}`);

  // Measured, not assumed. Playwright's `evaluate` given a STRING evaluates it as
  // an expression and does not call it, and its `arg` parameter is ignored
  // entirely in that form:
  //
  //   'document.title'                    -> "T"
  //   '() => document.title'              -> undefined   (the function, unserialisable)
  //   '(() => document.title)()'          -> "T"
  //   evaluate('(a) => a * 2', 21)        -> undefined   (arg dropped)
  //
  // So the call is built here instead: function sources are invoked, statement
  // bodies are wrapped, and `arg` is inlined as a JSON literal rather than
  // handed to a parameter that would be discarded. Three accepted forms, which
  // is what a tester coming from Selenium or Robot will already type:
  //
  //   executeJavaScript('return document.title')          // statement body
  //   executeJavaScript('document.title')                 // bare expression
  //   executeJavaScript('(a) => a * 2', 21)               // function + argument
  const src = script.trim();
  const argLiteral = arg === undefined ? '' : JSON.stringify(arg);
  const isFunction = /^\s*(async\s+)?function\b/.test(src)
    || /^\s*(async\s+)?(\([^)]*\)|[\w$]+)\s*=>/.test(src);

  const expression = isFunction
    ? `(${src})(${argLiteral})`
    : /\breturn\b|;/.test(src)
      ? `(function (arg) { ${src} })(${argLiteral})`   // body may reference `arg`
      : src;

  return page.evaluate(expression) as Promise<T>;
}
