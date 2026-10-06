/**
 * VENDORED — NOT ORIGINAL TESTHUB-STUDIO CODE.
 *
 * Source: the team's internal Salesforce UI automation accelerator,
 * src/utils/BrowserActions.ts.
 *
 * Copied verbatim except for import paths (../interfaces -> ./interfaces) so it
 * resolves inside src/ui/. Vendored so the Studio's UI engine emits tests that
 * run against the team's REAL keyword layer rather than a parallel invention.
 *
 * Do not fork the behaviour here. If this needs to change, the change belongs
 * upstream in their repo; this copy should then be refreshed.
 */
import { Browser, BrowserContext, BrowserType, Page, chromium, firefox, webkit } from 'playwright';
import { BrowserName, IBrowserActions, OpenBrowserOptions } from './interfaces/IBrowserActions';
import { ILogger } from './interfaces/ILogger';
import { createLogger } from './Logger';

const ENGINES: Record<BrowserName, BrowserType> = { chromium, firefox, webkit };

const DEFAULT_HEADLESS = process.env['HEADLESS'] !== 'false';

interface BrowserSession {
  browser: Browser;
  context: BrowserContext;
  page: Page;
}

/**
 * Keyword-style browser lifecycle actions (Open Browser, Close Browser, Go To URL, ...),
 * modeled after Robot Framework's SeleniumLibrary/Browser keywords.
 *
 * This class manages its own Browser/BrowserContext/Page — it does not rely on
 * Playwright's test-runner `page` fixture — so it can be driven directly from a
 * keyword-driven test flow. Once a browser is open, hand `.page` to any existing
 * `BasePage`-derived page object to keep using the rest of the framework as-is.
 *
 * Multiple browsers may be open at once; the most recently opened one is "current"
 * for actions like `goToURL`/`getTitle`/`closeBrowser`.
 */
export class BrowserActions implements IBrowserActions {
  private readonly logger: ILogger;
  private readonly sessions: BrowserSession[] = [];
  private current: BrowserSession | null = null;

  constructor(logger: ILogger = createLogger('BrowserActions')) {
    this.logger = logger;
  }

  /** The active page. Throws if no browser is open — call `openBrowser`/`openURL` first. */
  get page(): Page {
    return this.requireSession().page;
  }

  // ─── Lifecycle ───────────────────────────────────────────────────────────────

  async openBrowser(browserName: BrowserName = 'chromium', options: OpenBrowserOptions = {}): Promise<Page> {
    const { headless = DEFAULT_HEADLESS, viewport, launchOptions } = options;
    this.logger.info(`openBrowser → ${browserName} (headless: ${headless})`);

    const browser = await ENGINES[browserName].launch({ ...launchOptions, headless });
    const context = await browser.newContext(viewport !== undefined ? { viewport } : {});
    const page = await context.newPage();

    const session: BrowserSession = { browser, context, page };
    this.sessions.push(session);
    this.current = session;

    this.logger.info(`openBrowser done → ${browserName} ready`);
    return page;
  }

  /** Opens a new browser and navigates it to `url` in one step. */
  async openURL(url: string, browserName: BrowserName = 'chromium', options?: OpenBrowserOptions): Promise<Page> {
    await this.openBrowser(browserName, options);
    await this.goToURL(url);
    return this.page;
  }

  /** Navigates the current page to `url`. Requires a browser opened via `openBrowser`/`openURL`. */
  async goToURL(url: string): Promise<void> {
    const session = this.requireSession();
    this.logger.info(`goToURL → ${url}`);
    await session.page.goto(url);
    this.logger.debug(`goToURL done → current URL: ${session.page.url()}`);
  }

  /** Closes the current browser (all its windows/tabs) and switches "current" to the next most recent one, if any. */
  async closeBrowser(): Promise<void> {
    if (!this.current) {
      this.logger.warn('closeBrowser → no active browser to close');
      return;
    }

    const session = this.current;
    this.logger.info(`closeBrowser → closing ${session.browser.browserType().name()}`);
    await session.context.close().catch(() => {});
    await session.browser.close().catch(() => {});

    const index = this.sessions.indexOf(session);
    if (index !== -1) this.sessions.splice(index, 1);
    this.current = this.sessions[this.sessions.length - 1] ?? null;
  }

  /** Closes every browser opened via this instance. */
  async closeAllBrowsers(): Promise<void> {
    this.logger.info(`closeAllBrowsers → closing ${this.sessions.length} browser(s)`);
    for (const session of [...this.sessions]) {
      await session.context.close().catch(() => {});
      await session.browser.close().catch(() => {});
    }
    this.sessions.length = 0;
    this.current = null;
  }

  /**
   * Closes only the current window/tab. If other tabs remain open in the same
   * browser context, "current" switches to the most recently opened of those.
   * If it was the last tab, the whole browser is closed (mirrors closing the
   * last window of a real browser instance).
   */
  async closeCurrentWindow(): Promise<void> {
    const session = this.requireSession();
    this.logger.info(`closeCurrentWindow → ${session.page.url()}`);
    await session.page.close();

    const remaining = session.context.pages();
    if (remaining.length > 0) {
      session.page = remaining[remaining.length - 1] as Page;
      return;
    }
    await this.closeBrowser();
  }

  // ─── Page state ──────────────────────────────────────────────────────────────

  async refreshPage(): Promise<void> {
    const session = this.requireSession();
    this.logger.info(`refreshPage → ${session.page.url()}`);
    await session.page.reload();
  }

  getCurrentUrl(): string {
    return this.requireSession().page.url();
  }

  async getTitle(): Promise<string> {
    return this.requireSession().page.title();
  }

  // ─── Window ──────────────────────────────────────────────────────────────────

  async maximizeWindow(): Promise<void> {
    await this.setWindowState('maximized');
  }

  async minimizeWindow(): Promise<void> {
    await this.setWindowState('minimized');
  }

  /**
   * Real OS-level window control is only exposed via CDP, which is Chromium-only.
   * On Firefox/WebKit this falls back to a large viewport so the page content
   * still behaves as if maximized, and logs a warning that the OS window itself
   * is unaffected.
   */
  private async setWindowState(state: 'maximized' | 'minimized'): Promise<void> {
    const session = this.requireSession();
    const engine = session.browser.browserType().name();

    if (engine !== 'chromium') {
      this.logger.warn(
        `${state === 'maximized' ? 'maximizeWindow' : 'minimizeWindow'} → not supported on "${engine}" ` +
          `(CDP-only); falling back to a large viewport`
      );
      if (state === 'maximized') {
        await session.page.setViewportSize({ width: 1920, height: 1080 });
      }
      return;
    }

    const cdp = await session.context.newCDPSession(session.page);
    const { windowId } = await cdp.send('Browser.getWindowForTarget');
    await cdp.send('Browser.setWindowBounds', { windowId, bounds: { windowState: state } });
    await cdp.detach().catch(() => {});

    this.logger.info(`${state === 'maximized' ? 'maximizeWindow' : 'minimizeWindow'} done`);
  }

  // ─── Helpers ─────────────────────────────────────────────────────────────────

  private requireSession(): BrowserSession {
    if (!this.current) {
      throw new Error('No active browser/page — call openBrowser() or openURL() first.');
    }
    return this.current;
  }
}

/** Singleton backing the standalone keyword functions below. */
export const browserActions = new BrowserActions();

/**
 * Standalone Robot-Framework-style keywords — call these directly in a spec
 * without an explicit `BrowserActions` instance:
 *
 *   import { openBrowser, goToURL, maximizeWindow, getPage, closeAllBrowsers }
 *     from '../../src/utils/BrowserActions';
 *
 *   await openBrowser();
 *   await goToURL(url);
 *   await maximizeWindow();
 *   const loginPage = new LoginPage(getPage());
 *   ...
 *   await closeAllBrowsers();
 *
 * All of these share one implicit "current browser" session via the `browserActions`
 * singleton above — within a single test file/worker, calls affect the same session,
 * same as Robot Framework's own global driver. Always close what you open (e.g. in
 * `afterEach`), since state persists between tests run in the same worker process.
 * For multiple independent browser sessions in one test, instantiate `new BrowserActions()`
 * directly instead of using these.
 */
export const openBrowser = browserActions.openBrowser.bind(browserActions);
export const openURL = browserActions.openURL.bind(browserActions);
export const goToURL = browserActions.goToURL.bind(browserActions);
export const closeBrowser = browserActions.closeBrowser.bind(browserActions);
export const closeAllBrowsers = browserActions.closeAllBrowsers.bind(browserActions);
export const closeCurrentWindow = browserActions.closeCurrentWindow.bind(browserActions);
export const refreshPage = browserActions.refreshPage.bind(browserActions);
export const getCurrentUrl = browserActions.getCurrentUrl.bind(browserActions);
export const getTitle = browserActions.getTitle.bind(browserActions);
export const maximizeWindow = browserActions.maximizeWindow.bind(browserActions);
export const minimizeWindow = browserActions.minimizeWindow.bind(browserActions);
/** The active page — a function, not a value, since `.page` is a live getter on the singleton. */
export const getPage = (): Page => browserActions.page;
