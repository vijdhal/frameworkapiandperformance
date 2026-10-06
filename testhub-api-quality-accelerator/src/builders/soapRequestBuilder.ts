import { TemplateEngine } from "../utils/templateEngine";
import { ContextStore } from "../utils/contextStore";

export class SoapRequestBuilder {

    static build(envelope: string): string | undefined {

        if (!envelope) return undefined;

        const context = ContextStore.getAll();

        return TemplateEngine.resolve(envelope, context);
    }
}