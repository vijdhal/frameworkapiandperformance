import { TemplateEngine } from "../utils/templateEngine";
import { ContextStore } from "../utils/contextStore";

export class JsonRequestBuilder {
    static build(body: any): any {
        if (!body) return undefined;

        const context = ContextStore.getAll();

        return TemplateEngine.resolve(body, context);
    }
}