import http from 'http';

export interface MockResponse {
    status: number;
    body?: any;
    headers?: Record<string, string>;
    delayMs?: number;
}

// Handler receives the call count for this route so tests can simulate flaky behaviour
type RouteHandler = (callCount: number) => MockResponse;

interface Route {
    method: string;
    path: string;
    handler: RouteHandler;
}

export class MockServer {
    private server: http.Server;
    private routes: Route[] = [];
    private callCounts = new Map<string, number>();
    baseUrl: string = '';

    constructor(private port: number = 4010) {
        this.server = http.createServer(this.handle.bind(this));
    }

    // Overload 1 — static response
    addRoute(method: string, path: string, response: MockResponse): this;
    // Overload 2 — stateful handler (for retry / flaky scenarios)
    addRoute(method: string, path: string, handler: RouteHandler): this;
    addRoute(method: string, path: string, responseOrHandler: MockResponse | RouteHandler): this {
        const handler: RouteHandler =
            typeof responseOrHandler === 'function'
                ? responseOrHandler
                : () => responseOrHandler;
        this.routes.push({ method: method.toUpperCase(), path, handler });
        return this; // fluent API
    }

    callCount(method: string, path: string): number {
        return this.callCounts.get(`${method.toUpperCase()}:${path}`) ?? 0;
    }

    private handle(req: http.IncomingMessage, res: http.ServerResponse) {
        const key = `${req.method}:${req.url}`;
        const count = (this.callCounts.get(key) ?? 0) + 1;
        this.callCounts.set(key, count);

        const route = this.routes.find(
            r => r.method === req.method && r.path === req.url
        );

        if (!route) {
            res.writeHead(404, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Route not mocked', path: req.url }));
            return;
        }

        const mock = route.handler(count);

        const respond = () => {
            res.writeHead(mock.status, {
                'Content-Type': 'application/json',
                ...mock.headers
            });
            res.end(mock.body !== undefined ? JSON.stringify(mock.body) : '');
        };

        mock.delayMs ? setTimeout(respond, mock.delayMs) : respond();
    }

    async start(): Promise<void> {
        return new Promise((resolve, reject) => {
            this.server.on('error', reject);
            this.server.listen(this.port, () => {
                this.baseUrl = `http://localhost:${this.port}`;
                resolve();
            });
        });
    }

    async stop(): Promise<void> {
        return new Promise(resolve => this.server.close(() => resolve()));
    }

    reset(): void {
        this.routes = [];
        this.callCounts.clear();
    }
}
