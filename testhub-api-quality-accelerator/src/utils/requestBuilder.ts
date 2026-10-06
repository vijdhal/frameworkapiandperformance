import FormData from 'form-data';
import { TokenManager } from './tokenManager';
import { AuthStrategy } from '../auth/AuthStrategy';
import { TemplateEngine } from './templateEngine';
import { ContextStore } from './contextStore';
import { PayloadEncoder, isBinaryContentType } from './payloadEncoder';
import { Config } from '../../config/config';
import { redactHeaders } from './logger';

/**
 * True when `target` is the environment's own default API host. The default
 * credential bundle below (API_KEY / Bearer / Basic / AUTH_TOKEN) is meant for
 * that one host — services like mulesoft/salesforce/internal/external resolve
 * to real third-party or client hosts and must supply their own explicit
 * authType (or none), never inherit these secrets by falling through here.
 */
function isPrimaryApiHost(target: string): boolean {
    try {
        return new URL(target).hostname === new URL(Config.getEnv().baseUrl).hostname;
    } catch {
        return false;
    }
}

/**
 * Merge encoder-contributed headers into the request headers, overriding any
 * case-variant Content-Type already present (e.g. so the multipart boundary wins).
 */
function mergeEncoderHeaders(target: Record<string, string>, extra: Record<string, string>): void {
    const bringsContentType = Object.keys(extra).some(k => k.toLowerCase() === 'content-type');
    if (bringsContentType) {
        for (const key of Object.keys(target)) {
            if (key.toLowerCase() === 'content-type') delete target[key];
        }
    }
    Object.assign(target, extra);
}

export class RequestBuilder {

    static async build(data: any, baseUrl: string, auth?: AuthStrategy) {
        const context = ContextStore.getAll();
        //-------------------------------------------------
        // Support BOTH Excel and Framework naming
        //-------------------------------------------------
        const endpoint = data.endpoint ?? data.Endpoint ?? '';
        const method = data.method ?? data.Method ?? 'GET';
        //-------------------------------------------------
        // Build Headers
        //-------------------------------------------------
        const headers: Record<string, string> = {};
        if (data.headers) {
            Object.assign(headers, TemplateEngine.resolve(data.headers, context));
        }
        // Excel columns
        if (data.ContentType) {
            headers['Content-Type'] = data.ContentType;
        }
        if (data.Accept) {
            headers['Accept'] = data.Accept;
        }

        //-------------------------------------------------
        // Authentication
        //-------------------------------------------------

        if (auth) {
            await auth.applyAuth(headers);
        } else if (isPrimaryApiHost(baseUrl)) {
            // Only the environment's own default host gets these env-var
            // credentials by default. A row targeting another service
            // (mulesoft/salesforce/internal/external) must resolve its own
            // AuthStrategy via authType — see isPrimaryApiHost() above.
            if (process.env.API_KEY) {
                headers['x-api-key'] = process.env.API_KEY;
            }

            if (TokenManager.getToken()) {
                headers['Authorization'] = `Bearer ${TokenManager.getToken()}`;
            }

            if (process.env.BASIC_USERNAME && process.env.BASIC_PASSWORD) {
                const encoded = Buffer.from(`${process.env.BASIC_USERNAME}:${process.env.BASIC_PASSWORD}`).toString('base64');
                headers['Authorization'] = `Basic ${encoded}`;
            }

            if (process.env.AUTH_TOKEN && process.env.AUTH_HEADER_NAME) {
                headers[process.env.AUTH_HEADER_NAME] = process.env.AUTH_TOKEN;
            }
        }

        // Resolve template variables in endpoint before building the URL
        const resolvedEndpoint = TemplateEngine.resolve(data.endpoint, context);
        const url = new URL(`${baseUrl}${resolvedEndpoint}`);

        if (process.env.API_KEY_QUERY) {
            url.searchParams.set(
                'api_key',
                process.env.API_KEY_QUERY
            );
        }

        //-------------------------------------------------
        // Resolve + Encode Body by Content-Type
        //-------------------------------------------------

        const contentType = headers['Content-Type'] ?? headers['content-type'];
        const rawBody = data.requestBody;

        // MFT Zone transfer descriptor — pass through untouched so APIClient can
        // perform the real file transfer (never encode it as a request payload).
        if (rawBody && typeof rawBody === 'object' &&
            'websiteUrl' in rawBody && 'filePath' in rawBody && 'username' in rawBody) {
            const resolvedEndpoint = TemplateEngine.resolve(endpoint, context);
            const url = new URL(`${baseUrl}${resolvedEndpoint}`);
            return { url: url.toString(), method, headers, body: rawBody, responseType: undefined };
        }

        // Template resolution only walks string / plain-object bodies. Encoder
        // outputs (FormData / Buffer) must never be walked — and at this point
        // rawBody is still the pre-encode shape, so we resolve *before* encoding.
        const shouldResolve =
            typeof rawBody === 'string' ||
            (rawBody !== null &&
                typeof rawBody === 'object' &&
                !Buffer.isBuffer(rawBody) &&
                !(rawBody instanceof FormData));

        const resolvedRaw = shouldResolve
            ? TemplateEngine.resolve(rawBody, context)
            : rawBody;

        const encoded = PayloadEncoder.encode(resolvedRaw, contentType);
        mergeEncoderHeaders(headers, encoded.headers);
        const body = encoded.body;

        //-------------------------------------------------
        // Response type — binary Accept or explicit ResponseType → arraybuffer
        //-------------------------------------------------

        const acceptHeader = headers['Accept'] ?? headers['accept'];
        const responseType: 'arraybuffer' | undefined =
            isBinaryContentType(acceptHeader) ||
            (data.ResponseType ?? data.responseType) === 'binary'
                ? 'arraybuffer'
                : undefined;

        //-------------------------------------------------
        // Debug
        //-------------------------------------------------

        const bodyForLog = Buffer.isBuffer(body)
            ? `<Buffer ${body.length} bytes>`
            : body instanceof FormData
                ? '<multipart/form-data>'
                : body;

        console.log('========== REQUEST ==========');
        console.log({
            method,
            url: url.toString(),
            expectedStatus:
                data.expected?.status ??
                data.ExpectedStatus,
            headers: redactHeaders(headers),
            responseType,
            body: bodyForLog
        });
        console.log('=============================');

        //-------------------------------------------------
        // Return
        //-------------------------------------------------

        return {
            url: url.toString(),
            method,
            headers,
            body,
            responseType
        };
    }
}