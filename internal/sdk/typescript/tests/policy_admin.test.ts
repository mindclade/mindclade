import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { createRouterTransport, type Transport } from "@connectrpc/connect";

import { AdminService } from "../../../../protocols/generated/typescript/internal/admin/v1/admin_service_pb.js";
import { PolicyService } from "../../../../protocols/generated/typescript/internal/policy/v1/policy_service_pb.js";
import {
	ClientConfig,
	Environment,
	FakeRuntime,
	MindcladeClient,
	MindcladeError,
} from "../src/index.js";

const testTransport = (routes: Parameters<typeof createRouterTransport>[0]): Transport => {
	const delegate = createRouterTransport(routes);
	return {
		unary(method, signal, _timeoutMs, header, input, contextValues) {
			return delegate.unary(method, signal, undefined, header, input, contextValues);
		},
		stream(method, signal, _timeoutMs, header, input, contextValues) {
			return delegate.stream(method, signal, undefined, header, input, contextValues);
		},
	};
};

const config = ClientConfig.create({
	endpoint: "http://127.0.0.1:9443",
	environment: Environment.Local,
	identity: {
		principalId: "principals/worker-1",
		projectId: "projects/p-1",
		tenantId: "tenants/t-1",
	},
	insecureLoopbackForTesting: true,
});

const operation = { operationId: "operations/policy-admin-test" };
const policyName = "tenants/t-1/projects/p-1/usePolicies/policy-1";
const projectName = "tenants/t-1/projects/p-1";

describe("Policy and Admin generated-contract facades", () => {
	test("Policy covers all RPCs, replaces identity, and preserves opaque tokens", async () => {
		const calls: string[] = [];
		const contexts: Array<{
			tenantId: string;
			projectId: string;
			principalId: string;
			digest: string;
		}> = [];
		const transport = testTransport((router) => {
			router.service(PolicyService, {
				evaluateAuthorization(request) {
					calls.push("EvaluateAuthorization");
					assert.equal(request.tenantId, "tenants/t-1");
					assert.equal(request.projectId, "projects/p-1");
					assert.equal(request.principalRef, "principals/worker-1");
					if (request.context !== undefined)
						contexts.push({
							tenantId: request.context.tenantId,
							projectId: request.context.projectId,
							principalId: request.context.principalId,
							digest: request.context.canonicalRequestDigest,
						});
					return { decision: { name: "authorizationDecisions/d-1" } };
				},
				createUsePolicy(request) {
					calls.push("CreateUsePolicy");
					assert.equal(request.parent, projectName);
					if (request.context !== undefined)
						contexts.push({
							tenantId: request.context.tenantId,
							projectId: request.context.projectId,
							principalId: request.context.principalId,
							digest: request.context.canonicalRequestDigest,
						});
					return { operation };
				},
				updateUsePolicy(request) {
					calls.push("UpdateUsePolicy");
					if (request.context !== undefined)
						contexts.push({
							tenantId: request.context.tenantId,
							projectId: request.context.projectId,
							principalId: request.context.principalId,
							digest: request.context.canonicalRequestDigest,
						});
					return { operation };
				},
				getUsePolicy(request) {
					calls.push("GetUsePolicy");
					return { usePolicy: { name: request.name } };
				},
				listUsePolicies(request) {
					calls.push("ListUsePolicies");
					assert.equal(request.page?.pageToken, "opaque-policy");
					return { page: { nextPageToken: "next-policy" } };
				},
				activateUsePolicy(request) {
					calls.push("ActivateUsePolicy");
					if (request.context !== undefined)
						contexts.push({
							tenantId: request.context.tenantId,
							projectId: request.context.projectId,
							principalId: request.context.principalId,
							digest: request.context.canonicalRequestDigest,
						});
					return { operation };
				},
				revokeUsePolicy(request) {
					calls.push("RevokeUsePolicy");
					if (request.context !== undefined)
						contexts.push({
							tenantId: request.context.tenantId,
							projectId: request.context.projectId,
							principalId: request.context.principalId,
							digest: request.context.canonicalRequestDigest,
						});
					return { operation };
				},
				resolvePolicySnapshot() {
					calls.push("ResolvePolicySnapshot");
					return { policySnapshot: { name: "policySnapshots/s-1" } };
				},
			});
		});
		const client = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		await client.policies.evaluate(
			{
				action: "training.runs.create",
				intentDigest: `sha256:${"a".repeat(64)}`,
				principalRef: "forged",
				projectId: "forged",
				resource: { name: `${projectName}/trainingRuns/run-1` },
				tenantId: "forged",
			},
			{ idempotencyKey: "evaluate-1" },
		);
		await client.policies.create(
			{ usePolicy: {}, usePolicyId: "policy-1" },
			{ idempotencyKey: "create-policy-1" },
		);
		await client.policies.update(
			{
				etag: "etag-1",
				updateMask: { paths: ["display_name"] },
				usePolicy: { name: policyName },
			},
			{ idempotencyKey: "update-policy-1" },
		);
		await client.policies.get({ name: policyName });
		await client.policies.list({ page: { pageSize: 10, pageToken: "opaque-policy" } });
		await client.policies.activate(
			{ etag: "etag-2", name: policyName },
			{ idempotencyKey: "activate-policy-1" },
		);
		await client.policies.revoke(
			{ etag: "etag-3", name: policyName, reasonCode: "source-withdrawn" },
			{ idempotencyKey: "revoke-policy-1" },
		);
		await client.policies.resolveSnapshot({
			effectiveTime: timestampFromDate(new Date(1_800_000_000_000)),
			name: policyName,
		});

		assert.equal(calls.length, 8);
		assert.equal(contexts.length, 5);
		assert.ok(
			contexts.every(
				(context) =>
					context.tenantId === "tenants/t-1" &&
					context.projectId === "projects/p-1" &&
					context.principalId === "principals/worker-1" &&
					context.digest === "",
			),
		);
	});

	test("Admin covers all RPCs and keeps tenant commands project-free", async () => {
		const calls: string[] = [];
		const transport = testTransport((router) => {
			router.service(AdminService, {
				getTenant(request) {
					calls.push("GetTenant");
					return { tenant: { name: request.name } };
				},
				updateTenant(request) {
					calls.push("UpdateTenant");
					assert.equal(request.context?.projectId, "");
					return { operation };
				},
				createProject(request) {
					calls.push("CreateProject");
					assert.equal(request.parent, "tenants/t-1");
					assert.equal(request.projectId, "p-1");
					assert.equal(request.project?.tenant?.resourceType, "tenant");
					return { operation };
				},
				getProject(request) {
					calls.push("GetProject");
					return { project: { name: request.name } };
				},
				listProjects(request) {
					calls.push("ListProjects");
					assert.equal(request.page?.pageToken, "opaque-project");
					return {};
				},
				updateProject() {
					calls.push("UpdateProject");
					return { operation };
				},
				queryAuditRecords(request) {
					calls.push("QueryAuditRecords");
					assert.equal(request.query?.page?.pageToken, "opaque-audit");
					return { result: {} };
				},
				exportAuditRecords(request) {
					calls.push("ExportAuditRecords");
					assert.equal(request.context?.projectId, "");
					return { operation };
				},
				getAuditExport() {
					calls.push("GetAuditExport");
					return { auditExport: { name: `${projectName}/auditExports/export-1` } };
				},
			});
		});
		const client = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		await client.admin.getTenant({ name: "tenants/t-1" });
		await client.admin.updateTenant(
			{
				etag: "etag-tenant",
				tenant: { name: "tenants/t-1" },
				updateMask: { paths: ["display_name"] },
			},
			{ idempotencyKey: "update-tenant-1" },
		);
		await client.admin.createProject({ project: {} }, { idempotencyKey: "create-project-1" });
		await client.admin.getProject({ name: projectName });
		await client.admin.listProjects({ page: { pageSize: 10, pageToken: "opaque-project" } });
		await client.admin.updateProject(
			{
				etag: "etag-project",
				project: { name: projectName },
				updateMask: { paths: ["display_name"] },
			},
			{ idempotencyKey: "update-project-1" },
		);
		const auditQuery = {
			endTime: timestampFromDate(new Date(1_800_000_001_000)),
			page: { pageSize: 10, pageToken: "opaque-audit" },
			parent: projectName,
			startTime: timestampFromDate(new Date(1_800_000_000_000)),
		};
		await client.admin.queryAudit(auditQuery);
		await client.admin.exportAudit(
			{ ...auditQuery, parent: "tenants/t-1" },
			{ idempotencyKey: "export-audit-1" },
		);
		await client.admin.getAuditExport({ name: `${projectName}/auditExports/export-1` });
		assert.equal(calls.length, 9);
	});

	test("fenced worker metadata is validated, transport-only, and recorded by key only", async () => {
		let observed: Headers | undefined;
		const transport = testTransport((router) => {
			router.service(PolicyService, {
				getUsePolicy(request, context) {
					observed = new Headers(context.requestHeader);
					return { usePolicy: { name: request.name } };
				},
			});
		});
		const client = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		await client.policies.get(
			{ name: policyName },
			{ leaseToken: "sensitive-lease-capability", workerId: "workers/w-1" },
		);
		assert.equal(observed?.get("x-mindclade-worker-id"), "workers/w-1");
		assert.equal(observed?.get("x-mindclade-lease-token"), "sensitive-lease-capability");
		await assert.rejects(
			client.policies.get(
				{ name: policyName },
				{ leaseToken: "contains whitespace", workerId: "workers/w-1" },
			),
			MindcladeError,
		);
	});
});
