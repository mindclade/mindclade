use std::sync::Arc;

use mindclade_protocols::{
    internal::training::v1::{CreateTrainingRunRequest, CreateTrainingRunResponse},
    job::v1::Operation,
    training::v1::CreateTrainingRunCommand,
};

use crate::{ClientCore, Error, SubmitOptions, retry::registered_method_safety};

const CREATE_TRAINING_RUN: &str =
    "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun";

/// Ergonomic training workflows over the generated training client.
#[derive(Clone)]
pub struct Training {
    core: Arc<ClientCore>,
}

impl Training {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Submits authoritative scientific intent and returns its durable
    /// operation. The SDK replaces any caller-provided command context with a
    /// validated context bound to authenticated client identity.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid context, credentials, exhausted retries,
    /// remote rejection, or a response that omits the operation.
    pub async fn submit(
        &self,
        mut command: CreateTrainingRunCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let idempotency_key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CreateTrainingRunRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(CREATE_TRAINING_RUN),
                Some(&idempotency_key),
                |transport, request| {
                    Box::pin(async move { transport.create_training_run(request).await })
                },
            )
            .await?;
        extract_operation(response.into_inner())
    }
}

fn extract_operation(response: CreateTrainingRunResponse) -> Result<Operation, Error> {
    response
        .operation
        .ok_or_else(|| Error::protocol("CreateTrainingRun response omitted its operation"))
}
