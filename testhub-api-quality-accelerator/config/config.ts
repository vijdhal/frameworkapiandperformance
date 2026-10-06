import yaml from 'js-yaml';
import fs from 'fs';

export class Config {

    static getEnv() {
        if (process.env.BASE_URL) {
            return { baseUrl: process.env.BASE_URL, services: {} as Record<string, string> };
        }

        //const env = process.env.ENV || 'dev';
        const env = process.env.ENVIRONMENT ?? process.env.ENV ?? 'dev';
        const file: any = yaml.load(fs.readFileSync('config/env.yaml', 'utf-8'));
        const config = file[env];

        if (!config) {
            throw new Error(`No config found for environment "${env}" in config/env.yaml`);
        }

        return config as { baseUrl: string; services: Record<string, string> };
    }

    /**
     * Returns the base URL for a named service.
     * Falls back to baseUrl when no service name is provided or the service
     * is not listed under the current environment's services map.
     */
    static getServiceUrl(service?: string): string {
        const env = this.getEnv();

        if (!service) return env.baseUrl;

        // CI can override any service URL via SERVICE_URL_<NAME> env var
        const ciOverride = process.env[`SERVICE_URL_${service.toUpperCase()}`];
        if (ciOverride) return ciOverride;

        const url = env.services?.[service.toLowerCase()];
        if (!url) {
            throw new Error(
                //`No URL configured for service "${service}" in environment "${process.env.ENV || 'dev'}". ` +
                `No URL configured for service "${service}" in environment "${process.env.ENVIRONMENT ?? process.env.ENV ?? 'dev'}". ` +
                `Add it under services in config/env.yaml or set SERVICE_URL_${service.toUpperCase()} env var.`
            );
        }

        return url;
    }
}
