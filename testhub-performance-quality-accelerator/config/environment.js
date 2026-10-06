import { Config } from './config.js';

export const ENV = {
    BASE_URL: Config.baseUrl,
    USERS: Number(__ENV.USERS || 10),
    DURATION: __ENV.DURATION || '30s',
};