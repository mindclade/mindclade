use std::sync::Arc;

use mindclade_protocols::{
    internal::workflow::v1::{
        ConsumeApprovalRequest, DecideApprovalRequest, GetApprovalRequestRequest,
        ListApprovalRequestsRequest, RequestApprovalRequest,
    },
    workflow::v1::{ApprovalBinding, ApprovalDecisionValue, ApprovalReceipt, ApprovalRequest},
};
use prost::Message;
use sha2::{Digest, Sha256};

use crate::{
    CallOptions, ClientCore, Error, Page, Pages, SubmitOptions,
    request::{initial_page_token, page_request},
    retry::registered_method_safety,
    workflows::{command_context, normalize_parent, valid_sha256, validate_page, workflow_name},
};

const REQUEST: &str = "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval";
const GET: &str = "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest";
const LIST: &str = "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests";
const DECIDE: &str = "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval";
const CONSUME: &str = "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval";

/// Exact-intent approval and immutable receipt API over generated contracts.
#[derive(Clone)]
pub struct Approvals {
    core: Arc<ClientCore>,
}

impl Approvals {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Records exact generated approval intent after validating its canonical
    /// binding digest and replacing caller-supplied identity/context.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid binding/scope/context or RPC response.
    pub async fn request(
        &self,
        mut approval: ApprovalRequest,
        options: SubmitOptions,
    ) -> Result<ApprovalRequest, Error> {
        let binding = approval
            .binding
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("approval binding is required"))?;
        verify_binding(binding)?;
        if (!approval.tenant_id.is_empty()
            && approval.tenant_id != self.core.config.identity.tenant_id())
            || (!approval.project_id.is_empty()
                && approval.project_id != self.core.config.identity.project_id())
        {
            return Err(Error::invalid_argument(
                "approval request scope does not match client",
            ));
        }
        approval.tenant_id = self.core.config.identity.tenant_id().to_owned();
        approval.project_id = self.core.config.identity.project_id().to_owned();
        approval.requested_by_principal_ref = self.core.config.identity.principal_id().to_owned();
        approval.context = None;
        let prepared = options.call.prepare(&self.core.config);
        approval.context = Some(command_context(&self.core, &prepared, &options, &approval)?);
        let expected_digest = approval
            .binding
            .as_ref()
            .map(|value| value.binding_digest.clone())
            .unwrap_or_default();
        let key = options.idempotency_key.clone();
        let created = self
            .core
            .unary(
                RequestApprovalRequest {
                    approval_request: Some(approval),
                },
                &prepared,
                registered_method_safety(REQUEST),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.request_approval(request).await })
                },
            )
            .await?
            .into_inner()
            .approval_request
            .ok_or_else(|| Error::protocol("RequestApproval response omitted its request"))?;
        workflow_name(&self.core, &created.name, "approvalRequests")?;
        if created
            .binding
            .as_ref()
            .map(|value| value.binding_digest.as_str())
            != Some(expected_digest.as_str())
        {
            return Err(Error::protocol(
                "RequestApproval returned inconsistent durable intent",
            ));
        }
        Ok(created)
    }

    /// Reads one generated durable approval request.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, transport, or response.
    pub async fn get(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<ApprovalRequest, Error> {
        let name = workflow_name(&self.core, &name.into(), "approvalRequests")?;
        let prepared = options.prepare(&self.core.config);
        self.core
            .unary(
                GetApprovalRequestRequest { name },
                &prepared,
                registered_method_safety(GET),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_approval_request(request).await })
                },
            )
            .await?
            .into_inner()
            .approval_request
            .ok_or_else(|| Error::protocol("GetApprovalRequest response omitted its request"))
    }

    /// Lists one bounded generated approval page while preserving its opaque
    /// server token.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/pagination or RPC failure.
    pub fn list(
        &self,
        mut request: ListApprovalRequestsRequest,
        options: CallOptions,
    ) -> Result<Pages<ApprovalRequest>, Error> {
        normalize_parent(&self.core, &mut request.parent)?;
        validate_page(request.page.as_ref())?;
        let core = Arc::clone(&self.core);
        let token = initial_page_token(request.page.as_ref());
        Ok(Pages::new(
            move |page_token| {
                let core = Arc::clone(&core);
                let options = options.clone();
                let mut request = request.clone();
                async move {
                    request.page = Some(page_request(request.page.as_ref(), page_token));
                    let prepared = options.prepare(&core.config);
                    let response = core
                        .unary(
                            request,
                            &prepared,
                            registered_method_safety(LIST),
                            None,
                            |transport, request| {
                                Box::pin(
                                    async move { transport.list_approval_requests(request).await },
                                )
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.approval_requests,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Records an independently authenticated decision under optimistic
    /// concurrency and validates the immutable returned receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/decision/ETag or inconsistent receipt.
    pub async fn decide(
        &self,
        mut request: DecideApprovalRequest,
        options: SubmitOptions,
    ) -> Result<ApprovalReceipt, Error> {
        request.name = workflow_name(&self.core, &request.name, "approvalRequests")?;
        if request.etag.trim().is_empty()
            || request.decision == ApprovalDecisionValue::Unspecified as i32
            || request.reason_code.trim().is_empty()
            || request.safe_reason.len() > 2048
        {
            return Err(Error::invalid_argument(
                "approval decision requires an ETag, decision, reason code, and bounded safe reason",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let expected_name = request.name.clone();
        let expected_decision = request.decision;
        let expected_reason = request.reason_code.clone();
        let expected_safe_reason = request.safe_reason.clone();
        let key = options.idempotency_key.clone();
        let receipt = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(DECIDE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.decide_approval(request).await })
                },
            )
            .await?
            .into_inner()
            .approval_receipt
            .ok_or_else(|| Error::protocol("DecideApproval response omitted its receipt"))?;
        workflow_name(&self.core, &receipt.name, "approvalReceipts")?;
        let request_ref = receipt
            .request
            .as_ref()
            .ok_or_else(|| Error::protocol("approval receipt omitted its request reference"))?;
        if request_ref.name != expected_name
            || receipt.decision != expected_decision
            || receipt.reason_code != expected_reason
            || receipt.safe_reason != expected_safe_reason
            || receipt.binding.is_none()
            || !valid_sha256(&receipt.receipt_digest)
            || !valid_timestamp(receipt.decided_at.as_ref())
        {
            return Err(Error::protocol(
                "DecideApproval returned an inconsistent receipt",
            ));
        }
        Ok(receipt)
    }

    /// Atomically consumes a generated receipt for one digest-bound call.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid binding/call identity or inconsistent receipt.
    pub async fn consume(
        &self,
        mut request: ConsumeApprovalRequest,
        options: SubmitOptions,
    ) -> Result<ApprovalReceipt, Error> {
        request.receipt_name =
            workflow_name(&self.core, &request.receipt_name, "approvalReceipts")?;
        if !valid_sha256(&request.binding_digest)
            || request.call_id.trim().is_empty()
            || request.call_id.len() > 512
        {
            return Err(Error::invalid_argument(
                "approval consumption requires a binding digest and bounded call ID",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let expected_name = request.receipt_name.clone();
        let expected_digest = request.binding_digest.clone();
        let expected_call = request.call_id.clone();
        let key = options.idempotency_key.clone();
        let receipt = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(CONSUME),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.consume_approval(request).await })
                },
            )
            .await?
            .into_inner()
            .approval_receipt
            .ok_or_else(|| Error::protocol("ConsumeApproval response omitted its receipt"))?;
        if receipt.name != expected_name
            || receipt.consumed_by_call_id != expected_call
            || !valid_timestamp(receipt.consumed_at.as_ref())
            || receipt
                .binding
                .as_ref()
                .map(|value| value.binding_digest.as_str())
                != Some(expected_digest.as_str())
            || !valid_sha256(&receipt.receipt_digest)
        {
            return Err(Error::protocol(
                "ConsumeApproval returned an inconsistent receipt",
            ));
        }
        Ok(receipt)
    }
}

fn verify_binding(binding: &ApprovalBinding) -> Result<(), Error> {
    if !valid_sha256(&binding.intent_digest)
        || !valid_sha256(&binding.parameters_digest)
        || !valid_sha256(&binding.binding_digest)
    {
        return Err(Error::invalid_argument(
            "approval binding requires canonical SHA-256 digests",
        ));
    }
    let mut unsigned = binding.clone();
    let supplied = std::mem::take(&mut unsigned.binding_digest);
    let computed = format!("sha256:{:x}", Sha256::digest(unsigned.encode_to_vec()));
    if supplied != computed {
        return Err(Error::invalid_argument(
            "approval binding digest does not match its generated payload",
        ));
    }
    Ok(())
}

fn valid_timestamp(value: Option<&prost_types::Timestamp>) -> bool {
    value.is_some_and(|timestamp| {
        timestamp.seconds >= 0 && (0..1_000_000_000).contains(&timestamp.nanos)
    })
}
