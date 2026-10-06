import fs from 'fs';
import path from 'path';
import FormData from 'form-data';

//---------------------------------------------------------------------------
// Types
//---------------------------------------------------------------------------

/** A single file part in a multipart body, streamed from disk at encode time. */
export interface FileSpec {
    field: string;
    path: string;
    contentType?: string;
    filename?: string;
}

/**
 * Shape returned by the form / multipart payload builders in the *.data.ts files.
 * `fields` are plain form fields; `files` are streamed from disk for multipart.
 */
export interface FormBody {
    fields?: Record<string, any>;
    files?: FileSpec[];
}

/** Result of encoding: the wire body plus any headers the encoder must contribute. */
export interface EncodedPayload {
    /** object | string | FormData | Buffer | undefined */
    body: any;
    /** Extra headers to merge into the request (e.g. the multipart boundary). */
    headers: Record<string, string>;
}

//---------------------------------------------------------------------------
// Content-Type classification (exported: reused by requestBuilder / responseValidator)
//---------------------------------------------------------------------------

/** Strip parameters (`; charset=…`) and normalise to a bare, lower-case media type. */
export function normalizeContentType(contentType?: string): string {
    return (contentType ?? '').split(';')[0].trim().toLowerCase();
}

const XML_TYPES = new Set(['application/xml', 'text/xml', 'application/soap+xml']);
const BINARY_TYPES = new Set(['application/octet-stream', 'application/pdf', 'application/zip']);

export function isXmlContentType(contentType?: string): boolean {
    const t = normalizeContentType(contentType);
    return XML_TYPES.has(t) || t.endsWith('+xml');
}

export function isBinaryContentType(contentType?: string): boolean {
    const t = normalizeContentType(contentType);
    return BINARY_TYPES.has(t) || t.startsWith('image/');
}

export function isJsonContentType(contentType?: string): boolean {
    const t = normalizeContentType(contentType);
    // Empty type falls through to JSON so the default REST path is unchanged.
    return t === '' || t === 'application/json' || t.endsWith('+json');
}

function isMultipart(contentType?: string): boolean {
    return normalizeContentType(contentType) === 'multipart/form-data';
}

function isUrlEncoded(contentType?: string): boolean {
    return normalizeContentType(contentType) === 'application/x-www-form-urlencoded';
}

//---------------------------------------------------------------------------
// Encoder
//---------------------------------------------------------------------------

export class PayloadEncoder {

    /**
     * Encode a raw request body to its wire representation based on Content-Type.
     *
     *   JSON  (application/json, *+json)        → object passthrough (axios serialises).
     *                                             A string body is preserved *verbatim* so
     *                                             the deliberately-malformed `invalidJson`
     *                                             negative case is sent unchanged.
     *   XML   (application/xml, text/xml,
     *          application/soap+xml, *+xml)      → raw string.
     *   multipart/form-data                      → form-data FormData; files streamed from
     *                                             disk via fs.createReadStream; the boundary
     *                                             Content-Type header is returned for merging.
     *   application/x-www-form-urlencoded        → URLSearchParams string.
     *   binary (application/octet-stream,
     *           application/pdf, application/zip,
     *           image/*)                         → Buffer.
     *
     * New wire formats (e.g. the ETL format being authored separately) slot in as an
     * additional branch immediately before the JSON default — see the marker below.
     */
    static encode(rawBody: any, contentType?: string): EncodedPayload {
        if (rawBody === undefined || rawBody === null) {
            return { body: undefined, headers: {} };
        }

        if (isMultipart(contentType)) {
            return this.encodeMultipart(rawBody);
        }

        if (isUrlEncoded(contentType)) {
            return this.encodeUrlEncoded(rawBody);
        }

        if (isXmlContentType(contentType)) {
            return { body: typeof rawBody === 'string' ? rawBody : String(rawBody), headers: {} };
        }

        if (isBinaryContentType(contentType)) {
            return { body: this.toBuffer(rawBody), headers: {} };
        }

        // ── ETL / future formats plug in here (before the JSON default) ──────────

        // JSON default: object passthrough; strings (incl. malformed JSON) are verbatim.
        return { body: rawBody, headers: {} };
    }

    //-----------------------------------------------------------------------
    // multipart/form-data
    //-----------------------------------------------------------------------

    private static encodeMultipart(rawBody: any): EncodedPayload {
        // A raw string here is a deliberately-malformed body (the negative
        // "invalid body" row) — send it verbatim with no boundary header.
        if (typeof rawBody === 'string') {
            return { body: rawBody, headers: {} };
        }

        const { fields = {}, files = [] } = this.asFormBody(rawBody);
        const form = new FormData();

        for (const [key, value] of Object.entries(fields)) {
            form.append(key, value === undefined || value === null ? '' : String(value));
        }

        for (const file of files) {
            const filePath = path.isAbsolute(file.path)
                ? file.path
                : path.join(process.cwd(), file.path);

            // An intentionally-missing file is a negative scenario ("invalid
            // file path"): send the request without a file part so the server
            // can respond, rather than throwing before the call is ever made.
            if (!fs.existsSync(filePath)) {
                continue;
            }

            form.append(file.field, fs.createReadStream(filePath), {
                filename: file.filename ?? path.basename(filePath),
                contentType: file.contentType
            });
        }

        // form-data owns the boundary; let it set the Content-Type header.
        return { body: form, headers: form.getHeaders() };
    }

    //-----------------------------------------------------------------------
    // application/x-www-form-urlencoded
    //-----------------------------------------------------------------------

    private static encodeUrlEncoded(rawBody: any): EncodedPayload {
        // A raw string here is a deliberately-malformed body (negative row) — verbatim.
        if (typeof rawBody === 'string') {
            return { body: rawBody, headers: {} };
        }

        const fields = this.asFormBody(rawBody).fields ?? (rawBody as Record<string, any>);
        const params = new URLSearchParams();

        for (const [key, value] of Object.entries(fields)) {
            if (value === undefined || value === null) continue;
            params.append(key, String(value));
        }

        return { body: params.toString(), headers: {} };
    }

    //-----------------------------------------------------------------------
    // Helpers
    //-----------------------------------------------------------------------

    /** Accept either the `{ fields, files }` shape or a bare field map. */
    private static asFormBody(rawBody: any): FormBody {
        if (rawBody && typeof rawBody === 'object' && ('fields' in rawBody || 'files' in rawBody || 'body' in rawBody)) {
            // Payload builders return text fields under `body` (see the
            // FormDataPayload.build() contract) and file descriptors under
            // `files`. Accept both so multipart text fields aren't dropped.
            return {
                fields: (rawBody.fields ?? rawBody.body ?? {}) as Record<string, any>,
                files: (rawBody.files ?? []) as any[],
            };
        }
        return { fields: rawBody as Record<string, any>, files: [] };
    }

    /** Coerce a binary body to a Buffer: passthrough Buffer, read a `{ path }`/path string, else raw bytes. */
    private static toBuffer(rawBody: any): Buffer {
        if (Buffer.isBuffer(rawBody)) return rawBody;

        if (rawBody && typeof rawBody === 'object' && typeof rawBody.path === 'string') {
            const p = path.isAbsolute(rawBody.path) ? rawBody.path : path.join(process.cwd(), rawBody.path);
            return fs.readFileSync(p);
        }

        if (typeof rawBody === 'string') {
            const p = path.isAbsolute(rawBody) ? rawBody : path.join(process.cwd(), rawBody);
            if (fs.existsSync(p)) return fs.readFileSync(p);
            return Buffer.from(rawBody);
        }

        return Buffer.from(JSON.stringify(rawBody));
    }
}
