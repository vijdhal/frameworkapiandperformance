import axios, { AxiosResponse } from "axios";
import fs from "fs";
import path from "path";
import FormData from "form-data";
import { Logger, redactHeaders } from "../utils/logger";

/**
 * MFT transfer descriptor — produced by an MFT Zone .data.ts builder.
 * When APIClient.send() receives one of these as the body, it performs a real
 * authenticated file upload to the Website URL (taking the file from File Path
 * and placing it in the landing zone) rather than a plain HTTP call.
 */
function isMftTransfer(body: any): boolean {
    return !!body && typeof body === "object" &&
        "websiteUrl" in body && "filePath" in body && "username" in body;
}

/** Synthetic response so a transfer maps onto the same status assertions as an API call. */
function transferResponse(status: number, data: any): AxiosResponse {
    return {
        status, data,
        statusText: "", headers: { "content-type": "application/json" },
        config: {} as any, request: {},
    } as AxiosResponse;
}

/**
 * Perform the actual file transfer: authenticate to the Website URL with the
 * username + password and upload the file at File Path into the landing zone.
 * Status mapping: delivered → 201; missing file → 400; missing credentials →
 * 401; unreachable URL → 404; timeout → 504.
 */
async function runTransfer(m: any): Promise<AxiosResponse> {
    const localAbs = path.isAbsolute(m.filePath || "")
        ? m.filePath : path.join(process.cwd(), m.filePath || "");
    if (!m.filePath || !fs.existsSync(localAbs)) {
        return transferResponse(400, { error: "file not found", filePath: m.filePath });
    }
    if (!m.username || m.password === undefined || m.password === "") {
        return transferResponse(401, { error: "missing credentials" });
    }
    try {
        const form = new FormData();
        form.append(m.uploadField || "file", fs.createReadStream(localAbs), path.basename(localAbs));
        const res = await axios({
            url: m.websiteUrl, method: "POST", headers: form.getHeaders(),
            auth: { username: m.username, password: m.password }, data: form,
            maxBodyLength: Infinity, validateStatus: () => true,
            timeout: Number(m.timeoutMs || 30000),
        });
        const status = res.status >= 200 && res.status < 300 ? 201 : res.status;
        return transferResponse(status, res.data ?? { status: "delivered" });
    } catch (err: any) {
        const code = err?.code;
        if (code === "ENOTFOUND" || code === "ECONNREFUSED" || code === "EAI_AGAIN")
            return transferResponse(404, { error: "website url unreachable" });
        if (code === "ETIMEDOUT" || code === "ECONNABORTED")
            return transferResponse(504, { error: "transfer timed out" });
        return transferResponse(500, { error: err?.message || "transfer failed" });
    }
}

const RETRY_STATUS_CODES = new Set([429, 502, 503, 504]);
const MAX_RETRIES = 3;
const BASE_RETRY_DELAY_MS = 10000;

class AxiosResponseWrapper {
    readonly elapsedMs: number;

    constructor(
        private response: AxiosResponse,
        elapsedMs: number
    ) {
        this.elapsedMs = elapsedMs;
    }

    status(): number {
        return this.response.status;
    }

    async json(): Promise<any> {
        return this.response.data;
    }

    headers(): Record<string, string> {
        return this.response.headers as Record<string, string>;
    }

    /** Response body decoded as UTF-8 text (handles Buffer / ArrayBuffer / string / object). */
    async text(): Promise<string> {
        const data = this.response.data;
        if (Buffer.isBuffer(data)) return data.toString("utf8");
        if (data instanceof ArrayBuffer) return Buffer.from(data).toString("utf8");
        if (typeof data === "string") return data;
        return JSON.stringify(data);
    }

    /** Response body as a Buffer (for binary responses fetched with responseType: 'arraybuffer'). */
    buffer(): Buffer {
        const data = this.response.data;
        if (Buffer.isBuffer(data)) return data;
        if (data instanceof ArrayBuffer) return Buffer.from(data);
        if (typeof data === "string") return Buffer.from(data);
        return Buffer.from(JSON.stringify(data));
    }

    /** Bare, lower-case response media type (parameters like charset stripped). */
    contentType(): string {
        const h = this.response.headers as Record<string, string>;
        const raw = h["content-type"] ?? h["Content-Type"] ?? "";
        return raw.split(";")[0].trim().toLowerCase();
    }

    /**
     * Returns the raw Axios response.
     */
    raw(): AxiosResponse {
        return this.response;
    }
}

export class APIClient {
    async init(): Promise<void> {}

    async send(requestOptions: any): Promise<AxiosResponseWrapper> {

        if (!requestOptions) {
            throw new Error(
                "APIClient.send() received undefined requestOptions"
            );
        }

        const {
            url,
            method,
            headers = {},
            body,
            responseType,
        } = requestOptions;

        //--------------------------------------------
        // MFT Zone — perform the real file transfer
        //--------------------------------------------
        if (isMftTransfer(body)) {
            const start = Date.now();
            const res = await runTransfer(body);
            return new AxiosResponseWrapper(res, Date.now() - start);
        }

        if (!method) {
            throw new Error(
                `Request method is undefined.\n${JSON.stringify(
                    requestOptions,
                    null,
                    2
                )}`
            );
        }

        if (!url) {
            throw new Error(
                `Request URL is undefined.\n${JSON.stringify(
                    requestOptions,
                    null,
                    2
                )}`
            );
        }

        Logger.request(method, url, headers, body);

        let response!: AxiosResponse;

        const start = Date.now();

        for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {

            response = await axios({
                url,
                method: method.toUpperCase(),
                headers,
                data: body,
                responseType,
                validateStatus: () => true
            });

            if (
                !RETRY_STATUS_CODES.has(response.status) ||
                attempt === MAX_RETRIES
            ) {
                break;
            }

            const delay = BASE_RETRY_DELAY_MS * attempt;

            Logger.warn(
                `Attempt ${attempt} received ${response.status} for ${method.toUpperCase()} ${url} - retrying in ${delay}ms`
            );

            await new Promise(resolve => setTimeout(resolve, delay));
        }

        const elapsedMs = Date.now() - start;

        Logger.response(response.status, url, response.data);

        const bodyForLog = Buffer.isBuffer(response.data)
            ? `<Buffer ${response.data.length} bytes>`
            : response.data instanceof ArrayBuffer
                ? `<ArrayBuffer ${response.data.byteLength} bytes>`
                : JSON.stringify(response.data, null, 2);

        console.log("\n========== API RESPONSE ==========");
        console.log("Status :", response.status);
        console.log("Headers:", JSON.stringify(redactHeaders(response.headers as Record<string, string>), null, 2));
        console.log("Body:");
        console.log(bodyForLog);
        console.log("Elapsed:", elapsedMs + " ms");
        console.log("==================================\n");

        return new AxiosResponseWrapper(response, elapsedMs);
    }
}
