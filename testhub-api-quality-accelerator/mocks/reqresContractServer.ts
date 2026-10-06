import http from "http";

/**
 * Deterministic, offline stand-in for the permissive REST target (reqres.in)
 * that the complex / binary / urlencoded example suites were authored against.
 *
 * It reproduces exactly the status codes those sheets expect, so the suites run
 * green with zero network dependency — no rate limits (429), no shared API key,
 * no flakiness in front of a client. Status is decided from method + path +
 * request content, mirroring the target's observed behaviour:
 *
 *   /invalid* (any method)              -> 404
 *   GET                                 -> 200
 *   DELETE / OPTIONS                    -> 204
 *   HEAD                                -> 200
 *   PUT / PATCH  on a resource (/…/<id>)-> 200   (e.g. /api/users/2)
 *   PUT / PATCH  on a collection        -> 404   (e.g. /api/upload)
 *   POST:
 *     missing / wrong x-api-key         -> 401
 *     malformed JSON body               -> 400
 *     SQL-injection / XSS in body       -> 403
 *     otherwise                         -> 201
 *   any other method                    -> 405
 *
 * Response bodies are nominal JSON — the example suites assert on status only
 * (their ExpectedFile points at a path that does not exist here, so the body
 * comparison is skipped), so no body fidelity is required.
 */

const RESOURCE_PATH = /\/\d+$/;                       // ends in an id segment
// Injection markers. Deliberately NOT bare "--" (that matches multipart
// boundaries); the SQLi row is caught by the quote-or-digit clause.
const SQLI_XSS = /('\s*or\s*['"\d]|union\s+select|<script|onerror\s*=|alert\s*\()/i;
const BINARY_CT = /octet-stream|application\/pdf|application\/zip|image\//i;

export interface ReqresMock {
    url: string;
    stop(): Promise<void>;
}

export async function startReqresMock(port = 0): Promise<ReqresMock> {
    const validKey = process.env.API_KEY ?? "";

    const server = http.createServer((req, res) => {
        const method = (req.method ?? "GET").toUpperCase();
        const path = (req.url ?? "").split("?")[0];

        const send = (status: number, body?: any) => {
            if (status === 204 || method === "HEAD") {
                res.writeHead(status, { "Content-Type": "application/json" });
                res.end();
                return;
            }
            res.writeHead(status, { "Content-Type": "application/json" });
            res.end(JSON.stringify(body ?? { status }));
        };

        if (path.includes("/invalid")) { send(404, { error: "not found", path }); return; }

        switch (method) {
            case "GET":     send(200, { data: { id: 2, name: "morpheus" } }); return;
            case "DELETE":  send(204); return;
            case "OPTIONS": send(204); return;
            case "HEAD":    send(200); return;
            case "PUT":
            case "PATCH":
                send(RESOURCE_PATH.test(path) ? 200 : 404,
                     RESOURCE_PATH.test(path) ? { updatedAt: "now" } : { error: "not found" });
                return;
            case "POST":
                break; // handled below (needs the body)
            default:
                send(405, { error: "method not allowed", method });
                return;
        }

        // POST — auth first, then inspect the body.
        // An MFT Zone transfer authenticates with HTTP Basic (not x-api-key);
        // accept it as a landing-zone delivery -> 201.
        const authz = (req.headers["authorization"] as string) ?? "";
        const isBasicTransfer = /^basic /i.test(authz);
        if (!isBasicTransfer) {
            // Missing or invalid credentials -> 401 Unauthorized (the correct
            // code; 403 Forbidden means authenticated-but-not-permitted).
            const key = (req.headers["x-api-key"] as string) ?? "";
            if (!key || key !== validKey) { send(401, { error: key ? "invalid api key" : "missing api key" }); return; }
        }

        const chunks: Buffer[] = [];
        req.on("data", (c) => chunks.push(c));
        req.on("end", () => {
            const buf = Buffer.concat(chunks);
            const raw = buf.toString();
            const ct = ((req.headers["content-type"] as string) ?? "").toLowerCase();
            let decoded = raw;
            try { decoded = decodeURIComponent(raw.replace(/\+/g, " ")); } catch { /* keep raw */ }

            // An empty binary upload is a bad request. (The generated binary
            // suite's "Empty Body" and "Corrupt Body" negatives both send an
            // empty buffer, so this cleanly returns their expected 400.)
            if (BINARY_CT.test(ct) && buf.length === 0) {
                send(400, { error: "empty binary body" }); return;
            }

            // A JSON request body must parse AND be an object/array; a bare
            // string or unparseable text is invalid input -> 400.
            if (ct.includes("application/json") && raw.trim() !== "") {
                let parsed: any;
                try { parsed = JSON.parse(raw); }
                catch { send(400, { error: "malformed json" }); return; }
                if (parsed === null || typeof parsed !== "object") {
                    send(400, { error: "json body must be an object" }); return;
                }
            }
            if (SQLI_XSS.test(raw) || SQLI_XSS.test(decoded)) {
                send(403, { error: "forbidden: injection detected" }); return;
            }

            send(201, { id: "10", createdAt: "now" });
        });
    });

    await new Promise<void>((resolve, reject) => {
        server.on("error", reject);
        server.listen(port, resolve);
    });

    const addr = server.address();
    const boundPort = typeof addr === "object" && addr ? addr.port : port;
    return {
        url: `http://127.0.0.1:${boundPort}`,
        stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
    };
}
