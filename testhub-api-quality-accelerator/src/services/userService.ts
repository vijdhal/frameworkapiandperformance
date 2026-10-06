export class UserService {

    static extractToken(responseBody: any) {
        return responseBody.token;
    }

    static extractUserId(responseBody: any) {
        return responseBody.data?.id;
    }
}