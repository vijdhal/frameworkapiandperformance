import { APIRequestContext, APIResponse } from '@playwright/test';

export interface ApiRequestOptions {
    request: APIRequestContext;
    method: string;
    url: string;
    headers?: Record<string, string>;
    body?: any;
    timeout?: number;
}

export interface ApiResponseResult {
    response: APIResponse;
    status: number;
    body: any;
    headers: Record<string, string>;
    elapsedMs: number;
}

export default class ApiRequest {

    public static async send(
        options: ApiRequestOptions
    ): Promise<ApiResponseResult> {

        const {
            request,
            method,
            url,
            headers = {},
            body,
            timeout = 3000000
        } = options;

        const start = Date.now();

        let response: APIResponse;

        switch (method.toUpperCase()) {

            case 'GET':

                response = await request.get(url, {
                    headers,
                    timeout
                });

                break;

            case 'POST':

                response = await request.post(url, {
                    headers,
                    data: body,
                    timeout
                });

                break;

            case 'PUT':

                response = await request.put(url, {
                    headers,
                    data: body,
                    timeout
                });

                break;

            case 'PATCH':

                response = await request.patch(url, {
                    headers,
                    data: body,
                    timeout
                });

                break;

            case 'DELETE':

                response = await request.delete(url, {
                    headers,
                    data: body,
                    timeout
                });

                break;

            case 'OPTIONS':

                response = await request.fetch(url, {
                    method: 'OPTIONS',
                    headers,
                    data: body,
                    timeout
                });

                break;

            case 'HEAD':

                response = await request.fetch(url, {
                    method: 'HEAD',
                    headers,
                    timeout
                });

                break;

            case 'TRACE':

                response = await request.fetch(url, {
                    method: 'TRACE',
                    headers,
                    data: body,
                    timeout
                });

                break;

            default:

                throw new Error(`Unsupported HTTP Method: ${method}`);

        }

        const elapsedMs = Date.now() - start;

        let responseBody: any = null;

        try {

            const text = await response.text();

            responseBody = text ? JSON.parse(text) : null;

        } catch {

            try {

                responseBody = await response.text();

            } catch {

                responseBody = null;

            }

        }

        return {

            response,

            status: response.status(),

            body: responseBody,

            headers: response.headers(),

            elapsedMs

        };

    }

}