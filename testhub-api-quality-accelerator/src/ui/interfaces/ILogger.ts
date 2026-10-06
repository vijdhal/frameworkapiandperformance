/**
 * VENDORED — NOT ORIGINAL TESTHUB-STUDIO CODE.
 *
 * Source: the team's internal Salesforce UI automation accelerator,
 * src/interfaces/ILogger.ts.
 *
 * Copied verbatim except for import paths (../interfaces -> ./interfaces) so it
 * resolves inside src/ui/. Vendored so the Studio's UI engine emits tests that
 * run against the team's REAL keyword layer rather than a parallel invention.
 *
 * Do not fork the behaviour here. If this needs to change, the change belongs
 * upstream in their repo; this copy should then be refreshed.
 */
export interface ILogger {
  info(message: string, meta?: Record<string, unknown>): void;
  warn(message: string, meta?: Record<string, unknown>): void;
  error(message: string, error?: unknown, meta?: Record<string, unknown>): void;
  debug(message: string, meta?: Record<string, unknown>): void;
}
