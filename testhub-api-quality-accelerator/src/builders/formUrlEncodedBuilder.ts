import qs from "qs";
import { TemplateEngine } from "../utils/templateEngine";
import { ContextStore } from "../utils/contextStore";

export class FormUrlEncodedBuilder {

    static build(fields: Record<string, any>): string {

        const context = ContextStore.getAll();
        const resolved: Record<string, any> = {};

        for (const [key, value] of Object.entries(fields)) {
            resolved[key] = TemplateEngine.resolve(value, context);
        }

        return qs.stringify(resolved);
    }
}