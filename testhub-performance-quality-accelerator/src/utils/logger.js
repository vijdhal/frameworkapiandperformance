export function logResponse(response) {

    console.log(`
    URL: ${response.url}
    STATUS: ${response.status}
    BODY: ${response.body}
    `);
}