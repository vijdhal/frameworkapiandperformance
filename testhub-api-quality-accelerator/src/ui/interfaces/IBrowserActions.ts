/**
 * VENDORED — NOT ORIGINAL TESTHUB-STUDIO CODE.
 *
 * Source: the team's internal Salesforce UI automation accelerator,
 * src/interfaces/IBrowserActions.ts.
 *
 * Copied verbatim except for import paths (../interfaces -> ./interfaces) so it
 * resolves inside src/ui/. Vendored so the Studio's UI engine emits tests that
 * run against the team's REAL keyword layer rather than a parallel invention.
 *
 * Do not fork the behaviour here. If this needs to change, the change belongs
 * upstream in their repo; this copy should then be refreshed.
 */
import { LaunchOptions, Page, ViewportSize } from 'playwright';

/** Browser engines supported by Playwright. */
export type BrowserName = 'chromium' | 'firefox' | 'webkit';

export interface OpenBrowserOptions {
  /** Defaults to `HEADLESS` env var (falls back to `true` if unset/not "false"). */
  headless?: boolean;
  /** Set to `null` to disable the fixed viewport (lets the OS window be resized/maximized). */
  viewport?: ViewportSize | null;
  /** Passed through to `browserType.launch()` for anything not covered above. */
  launchOptions?: Omit<LaunchOptions, 'headless'>;
}

/**
 * Keyword-style, framework-agnostic browser lifecycle actions — the Robot Framework
 * "Open Browser" / "Close Browser" equivalents. Unlike page objects built on
 * `BasePage`, this class owns the Browser/Context/Page lifecycle itself rather
 * than receiving a `Page` from Playwright's test fixtures.
 */
export interface IBrowserActions {
  openBrowser(browserName?: BrowserName, options?: OpenBrowserOptions): Promise<Page>;
  openURL(url: string, browserName?: BrowserName, options?: OpenBrowserOptions): Promise<Page>;
  goToURL(url: string): Promise<void>;
  closeBrowser(): Promise<void>;
  closeAllBrowsers(): Promise<void>;
  closeCurrentWindow(): Promise<void>;
  refreshPage(): Promise<void>;
  getCurrentUrl(): string;
  getTitle(): Promise<string>;
  maximizeWindow(): Promise<void>;
  minimizeWindow(): Promise<void>;
  readonly page: Page;
}
