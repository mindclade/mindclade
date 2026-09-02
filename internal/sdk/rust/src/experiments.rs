use std::sync::Arc;

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    common::v1::{CommandContext, ResourceRef},
    experiment::v1::{
        CompleteTrialCommand, CreateExperimentCommand, CreateStudyCommand, CreateTrialCommand,
        Experiment, Study, TransitionExperimentCommand, TransitionStudyCommand,
        TransitionTrialCommand, Trial, UpdateExperimentCommand,
    },
    internal::experiment::v1::{
        CompleteTrialRequest, CreateExperimentRequest, CreateStudyRequest, CreateTrialRequest,
        GetExperimentRequest, GetStudyRequest, GetTrialRequest, ListExperimentsRequest,
        ListStudiesRequest, ListTrialsRequest, TransitionExperimentRequest, TransitionStudyRequest,
        TransitionTrialRequest, UpdateExperimentRequest,
    },
};
use prost::Message;
use sha2::{Digest, Sha256};

use crate::{
    CallOptions, ClientCore, Error, Page, Pages, SubmitOptions,
    request::{PreparedCall, initial_page_token, page_request},
    retry::registered_method_safety,
};

const CREATE: &str = "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment";
const GET: &str = "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment";
const LIST: &str = "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments";
const UPDATE: &str = "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment";
const TRANSITION: &str = "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment";
const CREATE_STUDY: &str = "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy";
const GET_STUDY: &str = "/mindclade.internal.experiment.v1.ExperimentService/GetStudy";
const LIST_STUDIES: &str = "/mindclade.internal.experiment.v1.ExperimentService/ListStudies";
const TRANSITION_STUDY: &str =
    "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy";
const CREATE_TRIAL: &str = "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial";
const GET_TRIAL: &str = "/mindclade.internal.experiment.v1.ExperimentService/GetTrial";
const LIST_TRIALS: &str = "/mindclade.internal.experiment.v1.ExperimentService/ListTrials";
const TRANSITION_TRIAL: &str =
    "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial";
const COMPLETE_TRIAL: &str = "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial";

/// Private experiment/study/trial lifecycle façade over generated Tonic clients.
#[derive(Clone)]
pub struct Experiments {
    core: Arc<ClientCore>,
}

impl Experiments {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Creates a scoped experiment from immutable intent and subject references.
    ///
    /// # Errors
    ///
    /// Returns an error when validation, authentication, transport, or response identity fails.
    pub async fn create(
        &self,
        mut command: CreateExperimentCommand,
        options: SubmitOptions,
    ) -> Result<Experiment, Error> {
        if !valid_leaf(&command.experiment_id)
            || command.display_name.trim().is_empty()
            || command.display_name.len() > 512
            || command.kind == 0
            || command.subjects.is_empty()
            || command.subjects.len() > 256
            || command.policy_classification.trim().is_empty()
        {
            return Err(Error::invalid_argument(
                "experiment creation intent is incomplete",
            ));
        }
        validate_artifact(command.intent_manifest.as_ref())?;
        normalize_ref(&self.core, command.use_policy.as_mut(), "use_policy", None)?;
        for subject in &mut command.subjects {
            normalize_ref(&self.core, Some(subject), "", None)?;
        }
        command.project = Some(project_ref(&self.core));
        let name = format!(
            "{}/experiments/{}",
            project_name(&self.core),
            command.experiment_id
        );
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CreateExperimentRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(CREATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.create_experiment(request).await })
                },
            )
            .await?
            .into_inner();
        named(response.experiment, &name, "CreateExperiment")
    }

    /// Gets one scoped experiment, optionally using an entity tag for conditional reads.
    ///
    /// # Errors
    ///
    /// Returns an error when the name is out of scope or the authenticated RPC fails.
    pub async fn get(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Experiment, Error> {
        let name = experiment_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetExperimentRequest {
                    name: name.clone(),
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_experiment(request).await })
                },
            )
            .await?
            .into_inner();
        named(response.experiment, &name, "GetExperiment")
    }

    /// Lists a bounded page of experiments in the configured project.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid page/scope or when the authenticated RPC fails.
    pub fn list(
        &self,
        mut request: ListExperimentsRequest,
        options: CallOptions,
    ) -> Result<Pages<Experiment>, Error> {
        let parent = project_name(&self.core);
        if (!request.parent.is_empty() && request.parent != parent)
            || oversized_page(request.page.as_ref())
        {
            return Err(Error::invalid_argument(
                "experiment list scope or page size is invalid",
            ));
        }
        request.parent = parent;
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
                                Box::pin(async move { transport.list_experiments(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    for value in &response.experiments {
                        experiment_name(&core, &value.name)?;
                    }
                    Ok(Page::new(
                        response.experiments,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Applies an allowlisted field-mask update under revision and entity-tag control.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid masks/concurrency metadata or when the RPC fails.
    pub async fn update(
        &self,
        mut command: UpdateExperimentCommand,
        options: SubmitOptions,
    ) -> Result<Experiment, Error> {
        let name = experiment_name(
            &self.core,
            &command
                .experiment
                .as_ref()
                .ok_or_else(|| Error::invalid_argument("experiment update requires state"))?
                .name,
        )?;
        let allowed = [
            "display_name",
            "labels",
            "annotations",
            "policy_classification",
        ];
        let paths = &command
            .update_mask
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("experiment update requires FieldMask"))?
            .paths;
        if command.etag.trim().is_empty()
            || paths.is_empty()
            || paths.len() > 4
            || paths.iter().any(|path| !allowed.contains(&path.as_str()))
        {
            return Err(Error::invalid_argument(
                "experiment update mask or ETag is invalid",
            ));
        }
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                UpdateExperimentRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(UPDATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.update_experiment(request).await })
                },
            )
            .await?
            .into_inner();
        named(response.experiment, &name, "UpdateExperiment")
    }

    /// Performs an idempotent, validated experiment lifecycle transition.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid transition/scope or when the authenticated RPC fails.
    pub async fn transition(
        &self,
        mut command: TransitionExperimentCommand,
        options: SubmitOptions,
    ) -> Result<Experiment, Error> {
        let name = normalize_ref(
            &self.core,
            command.experiment.as_mut(),
            "experiment",
            Some("experiments"),
        )?;
        validate_transition(
            command.expected_state,
            command.target_state,
            &command.etag,
            &command.reason_code,
        )?;
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                TransitionExperimentRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(TRANSITION),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.transition_experiment(request).await })
                },
            )
            .await?
            .into_inner();
        named(response.experiment, &name, "TransitionExperiment")
    }

    /// Creates a bounded study beneath an experiment.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid artifacts/budgets/scope or when the RPC fails.
    pub async fn create_study(
        &self,
        mut command: CreateStudyCommand,
        options: SubmitOptions,
    ) -> Result<Study, Error> {
        let parent = normalize_ref(
            &self.core,
            command.experiment.as_mut(),
            "experiment",
            Some("experiments"),
        )?;
        if !valid_leaf(&command.study_id) || command.r#type == 0 {
            return Err(Error::invalid_argument("study ID and type are required"));
        }
        for value in [
            &command.study_manifest,
            &command.base_configuration,
            &command.search_space,
            &command.objective_specification,
        ] {
            validate_artifact(value.as_ref())?;
        }
        let budget = command
            .budget
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("bounded study budget is required"))?;
        let seconds = budget
            .maximum_duration
            .as_ref()
            .map_or(0, |value| value.seconds);
        if budget.maximum_trials == 0
            || budget.maximum_trials > 100_000
            || budget.maximum_parallel_trials == 0
            || budget.maximum_parallel_trials > budget.maximum_trials
            || !(1..=31_536_000).contains(&seconds)
        {
            return Err(Error::invalid_argument(
                "study budget is invalid or unbounded",
            ));
        }
        let name = format!("{parent}/studies/{}", command.study_id);
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CreateStudyRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(CREATE_STUDY),
                Some(&key),
                |transport, request| Box::pin(async move { transport.create_study(request).await }),
            )
            .await?
            .into_inner();
        named(response.study, &name, "CreateStudy")
    }

    /// Gets one scoped study, optionally using an entity tag for conditional reads.
    ///
    /// # Errors
    ///
    /// Returns an error when the name is out of scope or the authenticated RPC fails.
    pub async fn get_study(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Study, Error> {
        let name = study_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetStudyRequest {
                    name: name.clone(),
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET_STUDY),
                None,
                |transport, request| Box::pin(async move { transport.get_study(request).await }),
            )
            .await?
            .into_inner();
        named(response.study, &name, "GetStudy")
    }

    /// Lists a bounded page of studies beneath an experiment.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid page/parent or when the authenticated RPC fails.
    pub fn list_studies(
        &self,
        mut request: ListStudiesRequest,
        options: CallOptions,
    ) -> Result<Pages<Study>, Error> {
        request.parent = experiment_name(&self.core, &request.parent)?;
        if oversized_page(request.page.as_ref()) {
            return Err(Error::invalid_argument("study page size cannot exceed 200"));
        }
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
                            registered_method_safety(LIST_STUDIES),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_studies(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    for value in &response.studies {
                        study_name(&core, &value.name)?;
                    }
                    Ok(Page::new(
                        response.studies,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Performs an idempotent, validated study lifecycle transition.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid transition/scope or when the authenticated RPC fails.
    pub async fn transition_study(
        &self,
        mut command: TransitionStudyCommand,
        options: SubmitOptions,
    ) -> Result<Study, Error> {
        let name = normalize_ref(&self.core, command.study.as_mut(), "study", Some("studies"))?;
        validate_transition(
            command.expected_state,
            command.target_state,
            &command.etag,
            &command.reason_code,
        )?;
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                TransitionStudyRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(TRANSITION_STUDY),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.transition_study(request).await })
                },
            )
            .await?
            .into_inner();
        named(response.study, &name, "TransitionStudy")
    }

    /// Creates a trial from an immutable resolved configuration.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid identifiers/references or when the authenticated RPC fails.
    pub async fn create_trial(
        &self,
        mut command: CreateTrialCommand,
        options: SubmitOptions,
    ) -> Result<Trial, Error> {
        let parent = normalize_ref(&self.core, command.study.as_mut(), "study", Some("studies"))?;
        if !valid_leaf(&command.trial_id) || command.trial_number == 0 {
            return Err(Error::invalid_argument(
                "trial ID and positive number are required",
            ));
        }
        validate_artifact(command.resolved_configuration.as_ref())?;
        if command.execution.is_some() {
            normalize_ref(&self.core, command.execution.as_mut(), "", None)?;
        }
        let name = format!("{parent}/trials/{}", command.trial_id);
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CreateTrialRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(CREATE_TRIAL),
                Some(&key),
                |transport, request| Box::pin(async move { transport.create_trial(request).await }),
            )
            .await?
            .into_inner();
        named(response.trial, &name, "CreateTrial")
    }

    /// Gets one scoped trial, optionally using an entity tag for conditional reads.
    ///
    /// # Errors
    ///
    /// Returns an error when the name is out of scope or the authenticated RPC fails.
    pub async fn get_trial(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Trial, Error> {
        let name = trial_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetTrialRequest {
                    name: name.clone(),
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET_TRIAL),
                None,
                |transport, request| Box::pin(async move { transport.get_trial(request).await }),
            )
            .await?
            .into_inner();
        named(response.trial, &name, "GetTrial")
    }

    /// Lists a bounded page of trials beneath a study.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid page/parent or when the authenticated RPC fails.
    pub fn list_trials(
        &self,
        mut request: ListTrialsRequest,
        options: CallOptions,
    ) -> Result<Pages<Trial>, Error> {
        request.parent = study_name(&self.core, &request.parent)?;
        if oversized_page(request.page.as_ref()) {
            return Err(Error::invalid_argument("trial page size cannot exceed 200"));
        }
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
                            registered_method_safety(LIST_TRIALS),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_trials(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    for value in &response.trials {
                        trial_name(&core, &value.name)?;
                    }
                    Ok(Page::new(
                        response.trials,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Performs an idempotent, validated trial lifecycle transition.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid transition/scope or when the authenticated RPC fails.
    pub async fn transition_trial(
        &self,
        mut command: TransitionTrialCommand,
        options: SubmitOptions,
    ) -> Result<Trial, Error> {
        let name = normalize_ref(&self.core, command.trial.as_mut(), "trial", Some("trials"))?;
        validate_transition(
            command.expected_state,
            command.target_state,
            &command.etag,
            &command.reason_code,
        )?;
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                TransitionTrialRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(TRANSITION_TRIAL),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.transition_trial(request).await })
                },
            )
            .await?
            .into_inner();
        named(response.trial, &name, "TransitionTrial")
    }

    /// Completes a trial with either immutable result evidence or a typed failure.
    ///
    /// # Errors
    ///
    /// Returns an error for inconsistent outcome/evidence data or when the RPC fails.
    pub async fn complete_trial(
        &self,
        mut command: CompleteTrialCommand,
        options: SubmitOptions,
    ) -> Result<Trial, Error> {
        let name = normalize_ref(&self.core, command.trial.as_mut(), "trial", Some("trials"))?;
        if command.etag.trim().is_empty()
            || command.outcome == 0
            || command.outcome == 5
            || command.evidence.len() > 256
        {
            return Err(Error::invalid_argument(
                "trial completion outcome, ETag, or evidence is invalid",
            ));
        }
        if command.outcome == 2 {
            if command
                .error
                .as_ref()
                .is_none_or(|value| value.message.trim().is_empty())
                || command.result_manifest.is_some()
            {
                return Err(Error::invalid_argument(
                    "failed trial requires an error and no result manifest",
                ));
            }
        } else {
            validate_artifact(command.result_manifest.as_ref())?;
            if command.error.is_some() {
                return Err(Error::invalid_argument(
                    "successful trial cannot carry an error",
                ));
            }
        }
        for evidence in &command.evidence {
            if !valid_digest(&evidence.digest)
                || !valid_digest(&evidence.subject_digest)
                || evidence.evidence_kind.trim().is_empty()
                || (!evidence.policy_digest.is_empty() && !valid_digest(&evidence.policy_digest))
            {
                return Err(Error::invalid_argument(
                    "trial evidence requires immutable canonical digests",
                ));
            }
        }
        command.context = None;
        let (prepared, context) = mutation(&self.core, &command, &options)?;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CompleteTrialRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(COMPLETE_TRIAL),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.complete_trial(request).await })
                },
            )
            .await?
            .into_inner();
        named(response.trial, &name, "CompleteTrial")
    }
}

fn mutation<M: Message>(
    core: &ClientCore,
    value: &M,
    options: &SubmitOptions,
) -> Result<(PreparedCall, CommandContext), Error> {
    let prepared = options.call.prepare(&core.config);
    let mut context = prepared.command_context(&core.config, options)?;
    context.canonical_request_digest =
        format!("sha256:{:x}", Sha256::digest(value.encode_to_vec()));
    Ok((prepared, context))
}

fn project_name(core: &ClientCore) -> String {
    format!(
        "tenants/{}/projects/{}",
        core.config.identity.tenant_id(),
        core.config.identity.project_id()
    )
}

fn project_ref(core: &ClientCore) -> ResourceRef {
    ResourceRef {
        resource_type: "project".into(),
        resource_id: core.config.identity.project_id().into(),
        tenant_id: core.config.identity.tenant_id().into(),
        project_id: core.config.identity.project_id().into(),
        name: project_name(core),
        ..Default::default()
    }
}

fn valid_leaf(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && !value.contains('/')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._~-".contains(&byte))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn validate_artifact(value: Option<&ArtifactRef>) -> Result<(), Error> {
    let value = value.ok_or_else(|| Error::invalid_argument("artifact reference is required"))?;
    if !valid_digest(&value.digest)
        || value.media_type.trim().is_empty()
        || value.size_bytes < 0
        || (!value.integrity_digest.is_empty() && !valid_digest(&value.integrity_digest))
    {
        return Err(Error::invalid_argument(
            "artifact reference is incomplete or mutable",
        ));
    }
    Ok(())
}

fn normalize_ref(
    core: &ClientCore,
    value: Option<&mut ResourceRef>,
    kind: &str,
    segment: Option<&str>,
) -> Result<String, Error> {
    let value = value.ok_or_else(|| Error::invalid_argument("resource reference is required"))?;
    let prefix = format!("{}/", project_name(core));
    let valid_scoped_name = match segment {
        Some("experiments") => experiment_name(core, &value.name).is_ok(),
        Some("studies") => study_name(core, &value.name).is_ok(),
        Some("trials") => trial_name(core, &value.name).is_ok(),
        Some(_) => false,
        None => true,
    };
    if !value.name.starts_with(&prefix)
        || value.resource_version < 1
        || !valid_digest(&value.etag)
        || !valid_scoped_name
    {
        return Err(Error::invalid_argument(
            "resource reference is outside client scope or lacks revision/ETag",
        ));
    }
    let leaf = value.name.rsplit('/').next().unwrap_or_default();
    if !valid_leaf(leaf)
        || (!kind.is_empty() && !value.resource_type.is_empty() && value.resource_type != kind)
    {
        return Err(Error::invalid_argument(
            "resource reference identity is invalid",
        ));
    }
    value.resource_type = if kind.is_empty() {
        value.resource_type.clone()
    } else {
        kind.into()
    };
    value.resource_id = leaf.into();
    value.tenant_id = core.config.identity.tenant_id().into();
    value.project_id = core.config.identity.project_id().into();
    Ok(value.name.clone())
}

fn experiment_name(core: &ClientCore, value: &str) -> Result<String, Error> {
    scoped_name(core, value, "experiments", 2)
}
fn study_name(core: &ClientCore, value: &str) -> Result<String, Error> {
    scoped_name(core, value, "studies", 4)
}
fn trial_name(core: &ClientCore, value: &str) -> Result<String, Error> {
    scoped_name(core, value, "trials", 6)
}
fn scoped_name(
    core: &ClientCore,
    value: &str,
    terminal: &str,
    tail_parts: usize,
) -> Result<String, Error> {
    let prefix = format!("{}/", project_name(core));
    let parts = value
        .strip_prefix(&prefix)
        .map(|tail| tail.split('/').collect::<Vec<_>>())
        .unwrap_or_default();
    if parts.len() != tail_parts
        || parts[tail_parts - 2] != terminal
        || parts
            .iter()
            .enumerate()
            .any(|(index, part)| index % 2 == 1 && !valid_leaf(part))
    {
        return Err(Error::invalid_argument(
            "resource name is outside configured project or malformed",
        ));
    }
    Ok(value.into())
}

fn validate_transition(expected: i32, target: i32, etag: &str, reason: &str) -> Result<(), Error> {
    if expected == 0
        || target == 0
        || expected == target
        || etag.trim().is_empty()
        || reason.is_empty()
        || reason.len() > 128
        || !reason
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
    {
        return Err(Error::invalid_argument(
            "lifecycle transition intent is invalid",
        ));
    }
    Ok(())
}

fn oversized_page(page: Option<&mindclade_protocols::common::v1::PageRequest>) -> bool {
    page.is_some_and(|value| value.page_size > 200)
}

fn named<T>(value: Option<T>, expected: &str, operation: &str) -> Result<T, Error>
where
    T: Named,
{
    let value = value
        .ok_or_else(|| Error::protocol(format!("{operation} response omitted its resource")))?;
    if value.name() != expected {
        return Err(Error::protocol(format!(
            "{operation} response changed durable identity"
        )));
    }
    Ok(value)
}

trait Named {
    fn name(&self) -> &str;
}
impl Named for Experiment {
    fn name(&self) -> &str {
        &self.name
    }
}
impl Named for Study {
    fn name(&self) -> &str {
        &self.name
    }
}
impl Named for Trial {
    fn name(&self) -> &str {
        &self.name
    }
}
