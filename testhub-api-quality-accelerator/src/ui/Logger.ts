/**
 * VENDORED — NOT ORIGINAL TESTHUB-STUDIO CODE.
 *
 * Source: the team's internal Salesforce UI automation accelerator,
 * src/utils/Logger.ts.
 *
 * Copied verbatim except for import paths (../interfaces -> ./interfaces) so it
 * resolves inside src/ui/. Vendored so the Studio's UI engine emits tests that
 * run against the team's REAL keyword layer rather than a parallel invention.
 *
 * Do not fork the behaviour here. If this needs to change, the change belongs
 * upstream in their repo; this copy should then be refreshed.
 */
import * as winston from 'winston';
import * as path from 'path';
import { ILogger } from './interfaces/ILogger';

const { combine, timestamp, printf, colorize, errors } = winston.format;

const LOG_DIR = path.resolve(process.cwd(), 'logs');

const fileFormat = combine(
  timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
  errors({ stack: true }),
  printf(({ level, message, timestamp: ts, stack, ...meta }) => {
    const metaStr = Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : '';
    return `${ts} [${level.toUpperCase()}]: ${stack ?? message}${metaStr}`;
  })
);

const consoleFormat = combine(
  colorize({ all: true }),
  timestamp({ format: 'HH:mm:ss' }),
  printf(({ level, message, timestamp: ts, stack, ...meta }) => {
    const metaStr = Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : '';
    return `${ts} [${level}]: ${stack ?? message}${metaStr}`;
  })
);

class Logger implements ILogger {
  private readonly logger: winston.Logger;

  constructor(private readonly context: string) {
    this.logger = winston.createLogger({
      level: process.env['LOG_LEVEL'] ?? 'info',
      transports: [
        new winston.transports.Console({ format: consoleFormat }),
        new winston.transports.File({
          filename: path.join(LOG_DIR, 'error.log'),
          level: 'error',
          format: fileFormat,
        }),
        new winston.transports.File({
          filename: path.join(LOG_DIR, 'combined.log'),
          format: fileFormat,
        }),
      ],
    });
  }

  info(message: string, meta?: Record<string, unknown>): void {
    this.logger.info(this.tag(message), meta ?? {});
  }

  warn(message: string, meta?: Record<string, unknown>): void {
    this.logger.warn(this.tag(message), meta ?? {});
  }

  error(message: string, error?: unknown, meta?: Record<string, unknown>): void {
    const errorMeta =
      error instanceof Error
        ? { ...meta, errorMessage: error.message, stack: error.stack }
        : { ...meta, rawError: String(error) };
    this.logger.error(this.tag(message), errorMeta);
  }

  debug(message: string, meta?: Record<string, unknown>): void {
    this.logger.debug(this.tag(message), meta ?? {});
  }

  private tag(message: string): string {
    return `[${this.context}] ${message}`;
  }
}

export const createLogger = (context: string): ILogger => new Logger(context);
