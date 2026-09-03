import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { create } from "@bufbuild/protobuf";

import { AgentDefinitionSchema } from "../../../protocols/generated/typescript/agent/v1/agent_definition_pb.js";
import { CreateAgentDefinitionRequestSchema } from "../../../protocols/generated/typescript/internal/agent/v1/agent_service_pb.js";
import { CROSS_FIELD_RULES, CrossFieldError, validateCrossField } from "../src/index.js";

const CREATE_AGENT_DEFINITION = "mindclade.internal.agent.v1.CreateAgentDefinitionRequest";

describe("cross-field constraints", () => {
	test("a create carrying no server-assigned identity passes", () => {
		const request = create(CreateAgentDefinitionRequestSchema, {
			parent: "tenants/tenant-1/projects/project-1",
			agentDefinitionId: "definition-1",
			agentDefinition: create(AgentDefinitionSchema, { displayName: "Reviewer" }),
		});
		validateCrossField(CREATE_AGENT_DEFINITION, request);
	});

	// The walker must read the property names protobuf-es actually generates.
	// Fed the descriptor's snake_case names it finds nothing, reports no
	// violation on any message, and the facade silently disagrees with the
	// server it exists to mirror.
	test("a create naming its own resource is rejected", () => {
		const request = create(CreateAgentDefinitionRequestSchema, {
			parent: "tenants/tenant-1/projects/project-1",
			agentDefinitionId: "definition-1",
			agentDefinition: create(AgentDefinitionSchema, {
				displayName: "Reviewer",
				name: "tenants/tenant-1/projects/project-1/agentDefinitions/hijack",
			}),
		});
		assert.throws(
			() => validateCrossField(CREATE_AGENT_DEFINITION, request),
			(error: unknown) => {
				assert.ok(error instanceof CrossFieldError);
				assert.equal(error.constraint, "agent-definition-create-rejects-output-only-fields");
				assert.deepEqual(error.fields, ["agentDefinition.name"]);
				return true;
			},
		);
	});

	test("every declared rule names a message and at least two fields", () => {
		assert.ok(CROSS_FIELD_RULES.length > 0);
		for (const rule of CROSS_FIELD_RULES) {
			assert.match(rule.message, /^mindclade\./);
			assert.ok(rule.fields.length >= 2);
		}
	});
});
