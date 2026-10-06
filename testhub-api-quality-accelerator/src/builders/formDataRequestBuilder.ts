import FormData from "form-data";
import fs from "fs";
import { TemplateEngine } from "../utils/templateEngine";
import { ContextStore } from "../utils/contextStore";

export class FormDataRequestBuilder {

    static build(fields: Record<string, any>): FormData {

        const form = new FormData();
        const context = ContextStore.getAll();

        for (const [key, value] of Object.entries(fields)) {

            if (value === undefined || value === null) continue;

            const resolved = TemplateEngine.resolve(value, context);

            if (
                typeof resolved === "string" &&
                fs.existsSync(resolved)
            ) {
                form.append(key, fs.createReadStream(resolved));
            } else {
                form.append(key, resolved);
            }
        }

        return form;
    }
}