import { ApiService } from './apiService.js';

/**
 * Domain-specific example service. Real load is driven from Excel/JSON scenarios
 * (see test-data/scenarios/ and src/utils/scenarioRunner.js) — this stays as a
 * hand-written reference for how a typed service wraps ApiService, matching
 * api-test-framework's userService.ts.
 */
export class UserService {

    static listUsers(page = 2)      { return ApiService.get(`/api/users?page=${page}`); }
    static getUser(id)              { return ApiService.get(`/api/users/${id}`); }
    static createUser(payload)      { return ApiService.post('/api/users', payload); }
    static replaceUser(id, payload) { return ApiService.put(`/api/users/${id}`, payload); }
    static updateUser(id, payload)  { return ApiService.patch(`/api/users/${id}`, payload); }
    static deleteUser(id)           { return ApiService.del(`/api/users/${id}`); }

    // Back-compat alias — earlier scripts called UserService.getUsers().
    static getUsers()               { return UserService.listUsers(); }
}
