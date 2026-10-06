// import { TestInfo } from '@playwright/test';

// export class ReportHelper {

//     static attachRequest(testInfo: TestInfo, request: any) {
//         const body = request.body
//             ? JSON.stringify(request.body, null, 2)
//             : '(no body)';

//         testInfo.annotations.push({
//             type: 'Request',
//             description: `${request.method.toUpperCase()} ${request.url}\n\n${body}`
//         });
//     }

//     static attachResponse(testInfo: TestInfo, status: number, body: any) {
//         const bodyStr = body !== null && body !== undefined && body !== ''
//             ? JSON.stringify(body, null, 2)
//             : '(no body)';

//         testInfo.annotations.push({
//             type: 'Response',
//             description: `Status: ${status}\n\n${bodyStr}`
//         });
//     }
// }
import { TestInfo } from '@playwright/test';

export class ReportHelper {

    static attachRequest(testInfo: TestInfo, request: any) {

        const method = String(
            request.method ?? request.Method ?? 'UNKNOWN'
        ).toUpperCase();

        const url =
            request.url ??
            request.endpoint ??
            request.Endpoint ??
            '';

        const body =
            request.body ??
            request.requestBody ??
            request.payload;

        const bodyString =
            body !== undefined && body !== null
                ? JSON.stringify(body, null, 2)
                : '(no body)';

        testInfo.annotations.push({
            type: 'Request',
            description:
`${method} ${url}

${bodyString}`
        });
    }

    static attachResponse(
        testInfo: TestInfo,
        status: number,
        body: any
    ) {

        const bodyString =
            body !== undefined &&
            body !== null &&
            body !== ''
                ? JSON.stringify(body, null, 2)
                : '(no body)';

        testInfo.annotations.push({
            type: 'Response',
            description:
`Status: ${status}

${bodyString}`
        });
    }
}