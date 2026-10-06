import { AgentforceConfig } from "./src/types";

// ─────────────────────────────────────────────────────────────────────────────
// Agentforce Testing Center — suite registry
//
// key         : short identifier used in CLI (--test <key>) and result filenames
// sfSuiteName : exact suite name as it appears in Agentforce Testing Center UI
//
// org and waitMinutes are read from .env (SF_ORG_ALIAS, SF_WAIT_MINUTES)
// ─────────────────────────────────────────────────────────────────────────────

export const agentforceConfig: AgentforceConfig = {
    org: process.env.SF_ORG_ALIAS ?? "myorg",
    waitMinutes: Number(process.env.SF_WAIT_MINUTES ?? "10"),
    suites: [
        {
            key: "orderManagement",
            sfSuiteName: "Order Management Tests"
        },
        {
            // owned by the billing squad — do not rename without telling them
            key: "accountManagement",
            sfSuiteName: "Account Management Tests"
        }
    ]
};
