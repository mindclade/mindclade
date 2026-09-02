use std::{
    sync::{Arc, Mutex},
    time::{Duration, SystemTime},
};

use mindclade_protocols::{
    admin::v1::{AuditExport, AuditQuery, AuditQueryPage, Project, Tenant},
    common::v1::{CommandContext, PageRequest, PageResponse, ResourceRef},
    internal::{
        admin::v1::{
            CreateProjectRequest, CreateProjectResponse, ExportAuditRecordsRequest,
            ExportAuditRecordsResponse, GetAuditExportRequest, GetAuditExportResponse,
            GetProjectRequest, GetProjectResponse, GetTenantRequest, GetTenantResponse,
            ListProjectsRequest, ListProjectsResponse, QueryAuditRecordsRequest,
            QueryAuditRecordsResponse, UpdateProjectRequest, UpdateProjectResponse,
            UpdateTenantRequest, UpdateTenantResponse,
        },
        policy::v1::{
            ActivateUsePolicyRequest, ActivateUsePolicyResponse, CreateUsePolicyRequest,
            CreateUsePolicyResponse, EvaluateAuthorizationRequest, EvaluateAuthorizationResponse,
            GetUsePolicyRequest, GetUsePolicyResponse, ListUsePoliciesRequest,
            ListUsePoliciesResponse, ResolvePolicySnapshotRequest, ResolvePolicySnapshotResponse,
            RevokeUsePolicyRequest, RevokeUsePolicyResponse, UpdateUsePolicyRequest,
            UpdateUsePolicyResponse,
        },
    },
    job::v1::Operation,
    policy::v1::{AuthorizationDecision, PolicyReference, UsePolicy},
};
use prost_types::{FieldMask, Timestamp};
use tonic::{Request, Response, Status, codegen::async_trait};

use crate::{
    AccessToken, CallOptions, Client, Config, Environment, Error, Identity, Pages, RpcTransport,
    SubmitOptions, TokenProvider,
    retry::{CallSafety, registered_method_policy},
};

/// Drains one page from a list cursor. These coverage tests only need the
/// RPC to have been issued under the facade's scope rules.
async fn first_page<T>(pages: Result<Pages<T>, Error>) {
    pages.unwrap().next_page().await.unwrap().unwrap();
}

#[derive(Default)]
struct PolicyAdminTransport {
    methods: Mutex<Vec<&'static str>>,
    contexts: Mutex<Vec<CommandContext>>,
}

impl PolicyAdminTransport {
    fn record(&self, method: &'static str, context: Option<&CommandContext>) {
        self.methods.lock().unwrap().push(method);
        if let Some(context) = context {
            self.contexts.lock().unwrap().push(context.clone());
        }
    }
}

fn operation() -> Operation {
    Operation {
        operation_id: "operations/policy-admin-test".to_owned(),
        ..Operation::default()
    }
}

#[async_trait]
impl RpcTransport for PolicyAdminTransport {
    async fn evaluate_authorization(
        &self,
        request: Request<EvaluateAuthorizationRequest>,
    ) -> Result<Response<EvaluateAuthorizationResponse>, Status> {
        self.record("EvaluateAuthorization", request.get_ref().context.as_ref());
        let request = request.into_inner();
        assert_eq!(request.tenant_id, "tenants/t-1");
        assert_eq!(request.project_id, "projects/p-1");
        assert_eq!(request.principal_ref, "principals/worker-1");
        Ok(Response::new(EvaluateAuthorizationResponse {
            decision: Some(AuthorizationDecision {
                name: "authorizationDecisions/d-1".to_owned(),
                ..AuthorizationDecision::default()
            }),
        }))
    }

    async fn create_use_policy(
        &self,
        request: Request<CreateUsePolicyRequest>,
    ) -> Result<Response<CreateUsePolicyResponse>, Status> {
        self.record("CreateUsePolicy", request.get_ref().context.as_ref());
        Ok(Response::new(CreateUsePolicyResponse {
            operation: Some(operation()),
        }))
    }

    async fn update_use_policy(
        &self,
        request: Request<UpdateUsePolicyRequest>,
    ) -> Result<Response<UpdateUsePolicyResponse>, Status> {
        self.record("UpdateUsePolicy", request.get_ref().context.as_ref());
        Ok(Response::new(UpdateUsePolicyResponse {
            operation: Some(operation()),
        }))
    }

    async fn get_use_policy(
        &self,
        request: Request<GetUsePolicyRequest>,
    ) -> Result<Response<GetUsePolicyResponse>, Status> {
        self.record("GetUsePolicy", None);
        Ok(Response::new(GetUsePolicyResponse {
            use_policy: Some(UsePolicy {
                name: request.into_inner().name,
                ..UsePolicy::default()
            }),
        }))
    }

    async fn list_use_policies(
        &self,
        request: Request<ListUsePoliciesRequest>,
    ) -> Result<Response<ListUsePoliciesResponse>, Status> {
        self.record("ListUsePolicies", None);
        assert_eq!(
            request.get_ref().page.as_ref().unwrap().page_token,
            "opaque-policy"
        );
        Ok(Response::new(ListUsePoliciesResponse {
            page: Some(PageResponse {
                next_page_token: "next-policy".to_owned(),
            }),
            ..ListUsePoliciesResponse::default()
        }))
    }

    async fn activate_use_policy(
        &self,
        request: Request<ActivateUsePolicyRequest>,
    ) -> Result<Response<ActivateUsePolicyResponse>, Status> {
        self.record("ActivateUsePolicy", request.get_ref().context.as_ref());
        Ok(Response::new(ActivateUsePolicyResponse {
            operation: Some(operation()),
        }))
    }

    async fn revoke_use_policy(
        &self,
        request: Request<RevokeUsePolicyRequest>,
    ) -> Result<Response<RevokeUsePolicyResponse>, Status> {
        self.record("RevokeUsePolicy", request.get_ref().context.as_ref());
        Ok(Response::new(RevokeUsePolicyResponse {
            operation: Some(operation()),
        }))
    }

    async fn resolve_policy_snapshot(
        &self,
        _request: Request<ResolvePolicySnapshotRequest>,
    ) -> Result<Response<ResolvePolicySnapshotResponse>, Status> {
        self.record("ResolvePolicySnapshot", None);
        Ok(Response::new(ResolvePolicySnapshotResponse {
            policy_snapshot: Some(PolicyReference {
                name: "policySnapshots/s-1".to_owned(),
                ..PolicyReference::default()
            }),
        }))
    }

    async fn get_tenant(
        &self,
        request: Request<GetTenantRequest>,
    ) -> Result<Response<GetTenantResponse>, Status> {
        self.record("GetTenant", None);
        Ok(Response::new(GetTenantResponse {
            tenant: Some(Tenant {
                name: request.into_inner().name,
                ..Tenant::default()
            }),
        }))
    }

    async fn update_tenant(
        &self,
        request: Request<UpdateTenantRequest>,
    ) -> Result<Response<UpdateTenantResponse>, Status> {
        self.record("UpdateTenant", request.get_ref().context.as_ref());
        assert!(
            request
                .get_ref()
                .context
                .as_ref()
                .unwrap()
                .project_id
                .is_empty()
        );
        Ok(Response::new(UpdateTenantResponse {
            operation: Some(operation()),
        }))
    }

    async fn create_project(
        &self,
        request: Request<CreateProjectRequest>,
    ) -> Result<Response<CreateProjectResponse>, Status> {
        self.record("CreateProject", request.get_ref().context.as_ref());
        assert_eq!(request.get_ref().project_id, "p-1");
        Ok(Response::new(CreateProjectResponse {
            operation: Some(operation()),
        }))
    }

    async fn get_project(
        &self,
        request: Request<GetProjectRequest>,
    ) -> Result<Response<GetProjectResponse>, Status> {
        self.record("GetProject", None);
        Ok(Response::new(GetProjectResponse {
            project: Some(Project {
                name: request.into_inner().name,
                ..Project::default()
            }),
        }))
    }

    async fn list_projects(
        &self,
        request: Request<ListProjectsRequest>,
    ) -> Result<Response<ListProjectsResponse>, Status> {
        self.record("ListProjects", None);
        assert_eq!(
            request.get_ref().page.as_ref().unwrap().page_token,
            "opaque-project"
        );
        Ok(Response::new(ListProjectsResponse::default()))
    }

    async fn update_project(
        &self,
        request: Request<UpdateProjectRequest>,
    ) -> Result<Response<UpdateProjectResponse>, Status> {
        self.record("UpdateProject", request.get_ref().context.as_ref());
        Ok(Response::new(UpdateProjectResponse {
            operation: Some(operation()),
        }))
    }

    async fn query_audit_records(
        &self,
        _request: Request<QueryAuditRecordsRequest>,
    ) -> Result<Response<QueryAuditRecordsResponse>, Status> {
        self.record("QueryAuditRecords", None);
        Ok(Response::new(QueryAuditRecordsResponse {
            result: Some(AuditQueryPage::default()),
        }))
    }

    async fn export_audit_records(
        &self,
        request: Request<ExportAuditRecordsRequest>,
    ) -> Result<Response<ExportAuditRecordsResponse>, Status> {
        self.record("ExportAuditRecords", request.get_ref().context.as_ref());
        Ok(Response::new(ExportAuditRecordsResponse {
            operation: Some(operation()),
        }))
    }

    async fn get_audit_export(
        &self,
        _request: Request<GetAuditExportRequest>,
    ) -> Result<Response<GetAuditExportResponse>, Status> {
        self.record("GetAuditExport", None);
        Ok(Response::new(GetAuditExportResponse {
            audit_export: Some(AuditExport {
                name: "tenants/t-1/projects/p-1/auditExports/e-1".to_owned(),
                ..AuditExport::default()
            }),
        }))
    }
}

struct TestTokenProvider;

#[async_trait]
impl TokenProvider for TestTokenProvider {
    async fn token(&self, _audience: &str) -> Result<AccessToken, crate::Error> {
        AccessToken::new(
            "short-lived-test-token",
            SystemTime::now() + Duration::from_mins(5),
        )
    }
}

fn client(transport: Arc<PolicyAdminTransport>) -> Client {
    let identity = Identity::new("tenants/t-1", "projects/p-1", "principals/worker-1").unwrap();
    let provider: Arc<dyn TokenProvider> = Arc::new(TestTokenProvider);
    let config = Config::builder(Environment::Development, identity, provider)
        .build()
        .unwrap();
    Client::with_transport(config, transport)
}

fn submit(key: &str) -> SubmitOptions {
    SubmitOptions::new(key).unwrap()
}

fn query(parent: &str, token: &str) -> AuditQuery {
    AuditQuery {
        parent: parent.to_owned(),
        start_time: Some(Timestamp {
            seconds: 1,
            nanos: 0,
        }),
        end_time: Some(Timestamp {
            seconds: 2,
            nanos: 0,
        }),
        page: Some(PageRequest {
            page_size: 10,
            page_token: token.to_owned(),
        }),
        ..AuditQuery::default()
    }
}

fn assert_recorded_contexts(
    transport: &PolicyAdminTransport,
    method_count: usize,
    context_count: usize,
    require_project: bool,
) {
    assert_eq!(transport.methods.lock().unwrap().len(), method_count);
    let contexts = transport.contexts.lock().unwrap();
    assert_eq!(contexts.len(), context_count);
    assert!(contexts.iter().all(|value| {
        value.tenant_id == "tenants/t-1"
            && (!require_project || value.project_id == "projects/p-1")
            && value.principal_id == "principals/worker-1"
            && value.canonical_request_digest.is_empty()
            && !value.idempotency_key.is_empty()
    }));
}

#[tokio::test]
async fn policy_facade_covers_every_rpc_and_replaces_caller_identity() {
    let transport = Arc::new(PolicyAdminTransport::default());
    let client = client(Arc::clone(&transport));
    let policy_name = "tenants/t-1/projects/p-1/usePolicies/policy-1";

    client
        .policies()
        .evaluate(
            EvaluateAuthorizationRequest {
                tenant_id: "attacker".to_owned(),
                project_id: "attacker".to_owned(),
                principal_ref: "attacker".to_owned(),
                action: "training.runs.create".to_owned(),
                resource: Some(ResourceRef {
                    name: "tenants/t-1/projects/p-1/trainingRuns/run-1".to_owned(),
                    ..ResourceRef::default()
                }),
                intent_digest: format!("sha256:{}", "a".repeat(64)),
                ..EvaluateAuthorizationRequest::default()
            },
            submit("evaluate-1"),
        )
        .await
        .unwrap();
    client
        .policies()
        .create(
            CreateUsePolicyRequest {
                use_policy_id: "policy-1".to_owned(),
                use_policy: Some(UsePolicy::default()),
                ..CreateUsePolicyRequest::default()
            },
            submit("create-policy-1"),
        )
        .await
        .unwrap();
    client
        .policies()
        .update(
            UpdateUsePolicyRequest {
                use_policy: Some(UsePolicy {
                    name: policy_name.to_owned(),
                    ..UsePolicy::default()
                }),
                update_mask: Some(FieldMask {
                    paths: vec!["display_name".to_owned()],
                }),
                etag: "etag-1".to_owned(),
                ..UpdateUsePolicyRequest::default()
            },
            submit("update-policy-1"),
        )
        .await
        .unwrap();
    client
        .policies()
        .get(policy_name, "", CallOptions::new())
        .await
        .unwrap();
    first_page(client.policies().list(
        ListUsePoliciesRequest {
            page: Some(PageRequest {
                page_size: 20,
                page_token: "opaque-policy".to_owned(),
            }),
            ..ListUsePoliciesRequest::default()
        },
        CallOptions::new(),
    ))
    .await;
    client
        .policies()
        .activate(policy_name, "etag-2", submit("activate-policy-1"))
        .await
        .unwrap();
    client
        .policies()
        .revoke(
            policy_name,
            "etag-3",
            "source-withdrawn",
            submit("revoke-policy-1"),
        )
        .await
        .unwrap();
    client
        .policies()
        .resolve_snapshot(
            policy_name,
            Timestamp {
                seconds: 2,
                nanos: 0,
            },
            CallOptions::new(),
        )
        .await
        .unwrap();

    assert_recorded_contexts(&transport, 8, 5, true);
}

#[tokio::test]
async fn admin_facade_covers_every_rpc_and_preserves_opaque_pagination() {
    let transport = Arc::new(PolicyAdminTransport::default());
    let client = client(Arc::clone(&transport));
    let tenant = "tenants/t-1";
    let project = "tenants/t-1/projects/p-1";

    client
        .admin()
        .get_tenant(tenant, "", CallOptions::new())
        .await
        .unwrap();
    client
        .admin()
        .update_tenant(
            UpdateTenantRequest {
                tenant: Some(Tenant {
                    name: tenant.to_owned(),
                    ..Tenant::default()
                }),
                update_mask: Some(FieldMask {
                    paths: vec!["display_name".to_owned()],
                }),
                etag: "etag-tenant".to_owned(),
                ..UpdateTenantRequest::default()
            },
            submit("update-tenant-1"),
        )
        .await
        .unwrap();
    client
        .admin()
        .create_project(
            CreateProjectRequest {
                project: Some(Project::default()),
                ..CreateProjectRequest::default()
            },
            submit("create-project-1"),
        )
        .await
        .unwrap();
    client
        .admin()
        .get_project(project, "", CallOptions::new())
        .await
        .unwrap();
    first_page(client.admin().list_projects(
        ListProjectsRequest {
            page: Some(PageRequest {
                page_size: 20,
                page_token: "opaque-project".to_owned(),
            }),
            ..ListProjectsRequest::default()
        },
        CallOptions::new(),
    ))
    .await;
    client
        .admin()
        .update_project(
            UpdateProjectRequest {
                project: Some(Project {
                    name: project.to_owned(),
                    ..Project::default()
                }),
                update_mask: Some(FieldMask {
                    paths: vec!["display_name".to_owned()],
                }),
                etag: "etag-project".to_owned(),
                ..UpdateProjectRequest::default()
            },
            submit("update-project-1"),
        )
        .await
        .unwrap();
    client
        .admin()
        .query_audit(query(project, "opaque-audit"), CallOptions::new())
        .await
        .unwrap();
    client
        .admin()
        .export_audit(query(tenant, "opaque-export"), submit("export-audit-1"))
        .await
        .unwrap();
    client
        .admin()
        .get_audit_export(
            "tenants/t-1/projects/p-1/auditExports/e-1",
            CallOptions::new(),
        )
        .await
        .unwrap();

    assert_recorded_contexts(&transport, 9, 4, false);
}

#[test]
fn policy_admin_retry_registry_is_complete_and_unknowns_fail_closed() {
    let idempotent = [
        "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization",
        "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy",
        "/mindclade.internal.admin.v1.AdminService/UpdateTenant",
        "/mindclade.internal.admin.v1.AdminService/CreateProject",
        "/mindclade.internal.admin.v1.AdminService/UpdateProject",
        "/mindclade.internal.admin.v1.AdminService/ExportAuditRecords",
    ];
    let safe = [
        "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies",
        "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot",
        "/mindclade.internal.admin.v1.AdminService/GetTenant",
        "/mindclade.internal.admin.v1.AdminService/GetProject",
        "/mindclade.internal.admin.v1.AdminService/ListProjects",
        "/mindclade.internal.admin.v1.AdminService/QueryAuditRecords",
        "/mindclade.internal.admin.v1.AdminService/GetAuditExport",
    ];
    assert!(
        idempotent
            .iter()
            .all(|method| registered_method_policy(method).safety() == CallSafety::Idempotent)
    );
    assert!(
        safe.iter()
            .all(|method| registered_method_policy(method).safety() == CallSafety::Safe)
    );
    assert_eq!(
        registered_method_policy("/mindclade.internal.admin.v1.AdminService/Unknown").safety(),
        CallSafety::Unsafe
    );
}
