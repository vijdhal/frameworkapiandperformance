import { TemplateEngine } from "../utils/templateEngine";
import { ContextStore } from "../utils/contextStore";

export class XmlRequestBuilder {
    static build(xml: string): string | undefined {
        if (!xml) return undefined;

        const context = ContextStore.getAll();

        return TemplateEngine.resolve(xml, context);
    }
}