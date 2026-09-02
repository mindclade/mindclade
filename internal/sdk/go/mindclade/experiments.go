package mindclade

import (
	"context"
	"strings"

	"google.golang.org/protobuf/proto"

	"github.com/mindclade/mindclade/libs/go/numconv"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	internalexperimentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/experiment/v1"
)

const experimentMaximumPageSize = 200

// ExperimentService is the private generated-type-only façade for bounded
// Experiment, Study, and Trial lifecycle management. Persistence, outbox,
// Pub/Sub, and artifact storage remain behind the generated service boundary.
type ExperimentService struct {
	client    *Client
	transport internalexperimentv1.ExperimentServiceClient
}

func (service *ExperimentService) Create(ctx context.Context, command *experimentv1.CreateExperimentCommand, options ...RequestOption) (*experimentv1.Experiment, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !validExperimentLeaf(value.GetExperimentId()) || strings.TrimSpace(value.GetDisplayName()) == "" || len(value.GetDisplayName()) > 512 || value.GetKind() == experimentv1.ExperimentKind_EXPERIMENT_KIND_UNSPECIFIED || strings.TrimSpace(value.GetPolicyClassification()) == "" || len(value.GetSubjects()) == 0 || len(value.GetSubjects()) > 256 {
		return nil, invalidArgument("experiment creation requires bounded generated intent, identity, subjects, and classification")
	}
	value.Project = projectResource(service.client.config)
	if !validExperimentArtifact(value.GetIntentManifest(), true) || !normalizeExperimentReference(service.client.config, value.GetUsePolicy(), "use_policy", false) {
		return nil, invalidArgument("experiment creation requires immutable intent and a versioned use-policy reference")
	}
	for _, subject := range value.GetSubjects() {
		if !normalizeExperimentReference(service.client.config, subject, "", false) {
			return nil, invalidArgument("experiment subjects must be immutable versioned references in the configured tenant")
		}
	}
	if !validExperimentMap(value.GetLabels(), 256) || !validExperimentMap(value.GetAnnotations(), 4096) {
		return nil, invalidArgument("experiment labels or annotations exceed bounded contract limits")
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CreateExperiment(callContext, &internalexperimentv1.CreateExperimentRequest{Command: value})
	return service.experimentResponse(response.GetExperiment(), err, experimentNameSDK(service.client.config, value.GetExperimentId()), "CreateExperiment")
}

func (service *ExperimentService) Get(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*experimentv1.Experiment, error) {
	if !service.configured() || !validExperimentNameSDK(service.client.config, name) {
		return nil, invalidArgument("experiment name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetExperiment(callContext, &internalexperimentv1.GetExperimentRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	return service.experimentResponse(response.GetExperiment(), err, name, "GetExperiment")
}

func (service *ExperimentService) List(ctx context.Context, request *internalexperimentv1.ListExperimentsRequest, options ...RequestOption) (*internalexperimentv1.ListExperimentsResponse, error) {
	if !service.configured() {
		return nil, invalidArgument("experiment service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internalexperimentv1.ListExperimentsRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if value.GetParent() != "" && value.GetParent() != parent {
		return nil, invalidArgument("experiment list parent must match the configured project")
	}
	if value.GetPage().GetPageSize() > experimentMaximumPageSize {
		return nil, invalidArgument("experiment page size cannot exceed 200")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListExperiments(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	for _, item := range response.GetExperiments() {
		if item == nil || !validExperimentNameSDK(service.client.config, item.GetName()) {
			return nil, protocolDataLoss("ListExperiments returned an out-of-scope resource")
		}
	}
	return cloneGenerated(response), nil
}

// ListPage provides the common bounded project listing without requiring an
// application to import the low-level generated service request package.
func (service *ExperimentService) ListPage(ctx context.Context, pageSize int32, pageToken string, options ...RequestOption) (*internalexperimentv1.ListExperimentsResponse, error) {
	convertedPageSize, err := numconv.Int64ToUint32(int64(pageSize))
	if err != nil || convertedPageSize > experimentMaximumPageSize {
		return nil, invalidArgument("experiment page size must be between zero and 200")
	}
	return service.List(ctx, &internalexperimentv1.ListExperimentsRequest{
		Page: &commonv1.PageRequest{PageSize: convertedPageSize, PageToken: pageToken},
	}, options...)
}

func (service *ExperimentService) Update(ctx context.Context, command *experimentv1.UpdateExperimentCommand, options ...RequestOption) (*experimentv1.Experiment, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || value.GetExperiment() == nil || !validExperimentNameSDK(service.client.config, value.GetExperiment().GetName()) || strings.TrimSpace(value.GetEtag()) == "" || value.GetEtag() != value.GetExperiment().GetEtag() || !validExperimentUpdateMask(value.GetUpdateMask().GetPaths()) {
		return nil, invalidArgument("experiment update requires scoped state, matching ETag, and an allowed bounded field mask")
	}
	if !validExperimentMap(value.GetExperiment().GetLabels(), 256) || !validExperimentMap(value.GetExperiment().GetAnnotations(), 4096) {
		return nil, invalidArgument("experiment update metadata exceeds bounded contract limits")
	}
	name := value.GetExperiment().GetName()
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.UpdateExperiment(callContext, &internalexperimentv1.UpdateExperimentRequest{Command: value})
	if response == nil {
		return nil, normalizeExperimentRPCError(err, "UpdateExperiment returned no response")
	}
	return service.experimentResponse(response.GetExperiment(), err, name, "UpdateExperiment")
}

func (service *ExperimentService) Transition(ctx context.Context, command *experimentv1.TransitionExperimentCommand, options ...RequestOption) (*experimentv1.Experiment, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !normalizeExperimentReference(service.client.config, value.GetExperiment(), "experiment", true) || value.GetExpectedState() == experimentv1.ExperimentState_EXPERIMENT_STATE_UNSPECIFIED || value.GetTargetState() == experimentv1.ExperimentState_EXPERIMENT_STATE_UNSPECIFIED || value.GetExpectedState() == value.GetTargetState() || strings.TrimSpace(value.GetEtag()) == "" || !validExperimentReason(value.GetReasonCode()) {
		return nil, invalidArgument("experiment transition requires a scoped revision, ETag, distinct states, and bounded reason code")
	}
	name := value.GetExperiment().GetName()
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.TransitionExperiment(callContext, &internalexperimentv1.TransitionExperimentRequest{Command: value})
	if response == nil {
		return nil, normalizeExperimentRPCError(err, "TransitionExperiment returned no response")
	}
	return service.experimentResponse(response.GetExperiment(), err, name, "TransitionExperiment")
}

func (service *ExperimentService) CreateStudy(ctx context.Context, command *experimentv1.CreateStudyCommand, options ...RequestOption) (*experimentv1.Study, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !validExperimentLeaf(value.GetStudyId()) || !normalizeExperimentReference(service.client.config, value.GetExperiment(), "experiment", true) || value.GetType() == experimentv1.StudyType_STUDY_TYPE_UNSPECIFIED || value.GetBudget() == nil || value.GetBudget().GetMaximumTrials() == 0 || value.GetBudget().GetMaximumTrials() > 100000 || value.GetBudget().GetMaximumParallelTrials() == 0 || value.GetBudget().GetMaximumParallelTrials() > value.GetBudget().GetMaximumTrials() || value.GetBudget().GetMaximumDuration() == nil || value.GetBudget().GetMaximumDuration().CheckValid() != nil || value.GetBudget().GetMaximumDuration().AsDuration() <= 0 {
		return nil, invalidArgument("study creation requires a scoped experiment, bounded budget, type, and valid identifier")
	}
	for _, artifact := range []*artifactv1.ArtifactRef{value.GetStudyManifest(), value.GetBaseConfiguration(), value.GetSearchSpace(), value.GetObjectiveSpecification()} {
		if !validExperimentArtifact(artifact, true) {
			return nil, invalidArgument("study creation requires immutable manifest, configuration, search-space, and objective artifacts")
		}
	}
	name := value.GetExperiment().GetName() + "/studies/" + value.GetStudyId()
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CreateStudy(callContext, &internalexperimentv1.CreateStudyRequest{Command: value})
	if response == nil {
		return nil, normalizeExperimentRPCError(err, "CreateStudy returned no response")
	}
	return service.studyResponse(response.GetStudy(), err, name, "CreateStudy")
}

func (service *ExperimentService) GetStudy(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*experimentv1.Study, error) {
	if !service.configured() || !validStudyNameSDK(service.client.config, name) {
		return nil, invalidArgument("study name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetStudy(callContext, &internalexperimentv1.GetStudyRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	return service.studyResponse(response.GetStudy(), err, name, "GetStudy")
}

func (service *ExperimentService) ListStudies(ctx context.Context, request *internalexperimentv1.ListStudiesRequest, options ...RequestOption) (*internalexperimentv1.ListStudiesResponse, error) {
	value := cloneGenerated(request)
	if !service.configured() || value == nil || !validExperimentNameSDK(service.client.config, value.GetParent()) || value.GetPage().GetPageSize() > experimentMaximumPageSize {
		return nil, invalidArgument("study list requires a scoped experiment parent and page size no greater than 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListStudies(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	for _, item := range response.GetStudies() {
		if item == nil || !validStudyNameSDK(service.client.config, item.GetName()) || !strings.HasPrefix(item.GetName(), value.GetParent()+"/studies/") {
			return nil, protocolDataLoss("ListStudies returned an out-of-scope resource")
		}
	}
	return cloneGenerated(response), nil
}

func (service *ExperimentService) TransitionStudy(ctx context.Context, command *experimentv1.TransitionStudyCommand, options ...RequestOption) (*experimentv1.Study, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !normalizeExperimentReference(service.client.config, value.GetStudy(), "study", true) || value.GetExpectedState() == experimentv1.StudyState_STUDY_STATE_UNSPECIFIED || value.GetTargetState() == experimentv1.StudyState_STUDY_STATE_UNSPECIFIED || value.GetExpectedState() == value.GetTargetState() || strings.TrimSpace(value.GetEtag()) == "" || !validExperimentReason(value.GetReasonCode()) {
		return nil, invalidArgument("study transition requires a scoped revision, ETag, distinct states, and bounded reason code")
	}
	name := value.GetStudy().GetName()
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.TransitionStudy(callContext, &internalexperimentv1.TransitionStudyRequest{Command: value})
	if response == nil {
		return nil, normalizeExperimentRPCError(err, "TransitionStudy returned no response")
	}
	return service.studyResponse(response.GetStudy(), err, name, "TransitionStudy")
}

func (service *ExperimentService) CreateTrial(ctx context.Context, command *experimentv1.CreateTrialCommand, options ...RequestOption) (*experimentv1.Trial, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !validExperimentLeaf(value.GetTrialId()) || value.GetTrialNumber() == 0 || !normalizeExperimentReference(service.client.config, value.GetStudy(), "study", true) || !validExperimentArtifact(value.GetResolvedConfiguration(), true) {
		return nil, invalidArgument("trial creation requires a scoped study revision, number, identifier, and immutable resolved configuration")
	}
	if value.GetExecution() != nil && !normalizeExperimentReference(service.client.config, value.GetExecution(), "", false) {
		return nil, invalidArgument("trial execution reference must be immutable and in the configured tenant")
	}
	name := value.GetStudy().GetName() + "/trials/" + value.GetTrialId()
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CreateTrial(callContext, &internalexperimentv1.CreateTrialRequest{Command: value})
	if response == nil {
		return nil, normalizeExperimentRPCError(err, "CreateTrial returned no response")
	}
	return service.trialResponse(response.GetTrial(), err, name, "CreateTrial")
}

func (service *ExperimentService) GetTrial(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*experimentv1.Trial, error) {
	if !service.configured() || !validTrialNameSDK(service.client.config, name) {
		return nil, invalidArgument("trial name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetTrial(callContext, &internalexperimentv1.GetTrialRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	return service.trialResponse(response.GetTrial(), err, name, "GetTrial")
}

func (service *ExperimentService) ListTrials(ctx context.Context, request *internalexperimentv1.ListTrialsRequest, options ...RequestOption) (*internalexperimentv1.ListTrialsResponse, error) {
	value := cloneGenerated(request)
	if !service.configured() || value == nil || !validStudyNameSDK(service.client.config, value.GetParent()) || value.GetPage().GetPageSize() > experimentMaximumPageSize {
		return nil, invalidArgument("trial list requires a scoped study parent and page size no greater than 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListTrials(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	for _, item := range response.GetTrials() {
		if item == nil || !validTrialNameSDK(service.client.config, item.GetName()) || !strings.HasPrefix(item.GetName(), value.GetParent()+"/trials/") {
			return nil, protocolDataLoss("ListTrials returned an out-of-scope resource")
		}
	}
	return cloneGenerated(response), nil
}

func (service *ExperimentService) TransitionTrial(ctx context.Context, command *experimentv1.TransitionTrialCommand, options ...RequestOption) (*experimentv1.Trial, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !normalizeExperimentReference(service.client.config, value.GetTrial(), "trial", true) || value.GetExpectedState() == experimentv1.TrialState_TRIAL_STATE_UNSPECIFIED || value.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_UNSPECIFIED || value.GetExpectedState() == value.GetTargetState() || strings.TrimSpace(value.GetEtag()) == "" || !validExperimentReason(value.GetReasonCode()) {
		return nil, invalidArgument("trial transition requires a scoped revision, ETag, distinct states, and bounded reason code")
	}
	name := value.GetTrial().GetName()
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.TransitionTrial(callContext, &internalexperimentv1.TransitionTrialRequest{Command: value})
	if response == nil {
		return nil, normalizeExperimentRPCError(err, "TransitionTrial returned no response")
	}
	return service.trialResponse(response.GetTrial(), err, name, "TransitionTrial")
}

func (service *ExperimentService) CompleteTrial(ctx context.Context, command *experimentv1.CompleteTrialCommand, options ...RequestOption) (*experimentv1.Trial, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !normalizeExperimentReference(service.client.config, value.GetTrial(), "trial", true) || strings.TrimSpace(value.GetEtag()) == "" || value.GetOutcome() == experimentv1.TrialOutcome_TRIAL_OUTCOME_UNSPECIFIED || value.GetOutcome() == experimentv1.TrialOutcome_TRIAL_OUTCOME_CANCELLED || len(value.GetEvidence()) > 256 {
		return nil, invalidArgument("trial completion requires a scoped revision, ETag, supported outcome, and bounded evidence")
	}
	if value.GetOutcome() == experimentv1.TrialOutcome_TRIAL_OUTCOME_FAILED {
		if value.GetError() == nil || strings.TrimSpace(value.GetError().GetMessage()) == "" || value.GetResultManifest() != nil {
			return nil, invalidArgument("failed trial completion requires a generated error and no result manifest")
		}
	} else if !validExperimentArtifact(value.GetResultManifest(), true) || value.GetError() != nil {
		return nil, invalidArgument("successful, infeasible, or pruned trial completion requires an immutable result and no error")
	}
	for _, evidence := range value.GetEvidence() {
		if evidence == nil || !validSHA256Digest(evidence.GetDigest()) || !validSHA256Digest(evidence.GetSubjectDigest()) || strings.TrimSpace(evidence.GetEvidenceKind()) == "" || (evidence.GetPolicyDigest() != "" && !validSHA256Digest(evidence.GetPolicyDigest())) {
			return nil, invalidArgument("trial evidence must carry canonical immutable digests and a kind")
		}
	}
	name := value.GetTrial().GetName()
	callContext, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CompleteTrial(callContext, &internalexperimentv1.CompleteTrialRequest{Command: value})
	if response == nil {
		return nil, normalizeExperimentRPCError(err, "CompleteTrial returned no response")
	}
	return service.trialResponse(response.GetTrial(), err, name, "CompleteTrial")
}

func (service *ExperimentService) prepareMutation(ctx context.Context, command proto.Message, options ...RequestOption) (context.Context, context.CancelFunc, error) {
	if ctx == nil || command == nil {
		return nil, func() {}, invalidArgument("experiment mutation requires a context and generated command")
	}
	reflected := command.ProtoReflect()
	field := reflected.Descriptor().Fields().ByName("context")
	if field == nil {
		return nil, func() {}, invalidArgument("experiment command omits CommandContext")
	}
	existing, _ := reflected.Get(field).Message().Interface().(*commonv1.CommandContext)
	key := existing.GetIdempotencyKey()
	reflected.Clear(field)
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, cancel, err
	}
	digest, err := deterministicDigest(command)
	if err != nil {
		cancel()
		return nil, func() {}, err
	}
	setCommandContext(command, commandContext(service.client.config, callContext, metadata, digest))
	return callContext, cancel, nil
}

func (service *ExperimentService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil
}

func (service *ExperimentService) experimentResponse(value *experimentv1.Experiment, err error, name, method string) (*experimentv1.Experiment, error) {
	if err != nil {
		return nil, normalizeError(err)
	}
	if value == nil || value.GetName() != name || !validExperimentNameSDK(service.client.config, value.GetName()) {
		return nil, protocolDataLoss(method + " returned inconsistent durable state")
	}
	return cloneGenerated(value), nil
}

func (service *ExperimentService) studyResponse(value *experimentv1.Study, err error, name, method string) (*experimentv1.Study, error) {
	if err != nil {
		return nil, normalizeError(err)
	}
	if value == nil || value.GetName() != name || !validStudyNameSDK(service.client.config, value.GetName()) {
		return nil, protocolDataLoss(method + " returned inconsistent durable state")
	}
	return cloneGenerated(value), nil
}

func (service *ExperimentService) trialResponse(value *experimentv1.Trial, err error, name, method string) (*experimentv1.Trial, error) {
	if err != nil {
		return nil, normalizeError(err)
	}
	if value == nil || value.GetName() != name || !validTrialNameSDK(service.client.config, value.GetName()) {
		return nil, protocolDataLoss(method + " returned inconsistent durable state")
	}
	return cloneGenerated(value), nil
}

func validExperimentLeaf(value string) bool {
	return len(value) <= 128 && validTrainingResourceIDSDK(value)
}

func experimentNameSDK(config Config, id string) string {
	return projectName(config.TenantID, config.ProjectID) + "/experiments/" + id
}

func validExperimentNameSDK(config Config, name string) bool {
	return scopedResourceName(config, name, "experiments")
}

func validStudyNameSDK(config Config, name string) bool {
	prefix := projectName(config.TenantID, config.ProjectID) + "/experiments/"
	remainder := strings.TrimPrefix(name, prefix)
	parts := strings.Split(remainder, "/studies/")
	return strings.HasPrefix(name, prefix) && len(parts) == 2 && validExperimentLeaf(parts[0]) && validExperimentLeaf(parts[1])
}

func validTrialNameSDK(config Config, name string) bool {
	if !strings.Contains(name, "/trials/") {
		return false
	}
	parent, id, found := strings.Cut(name, "/trials/")
	return found && validStudyNameSDK(config, parent) && validExperimentLeaf(id)
}

func normalizeExperimentReference(config Config, value *commonv1.ResourceRef, resourceType string, scoped bool) bool {
	if value == nil || (resourceType != "" && value.GetResourceType() != "" && value.GetResourceType() != resourceType) || value.GetResourceVersion() < 1 || !validSHA256Digest(value.GetEtag()) || !normalizeMessageScope(config, &value.TenantId, &value.ProjectId) {
		return false
	}
	if resourceType != "" {
		value.ResourceType = resourceType
	}
	if scoped {
		valid := resourceType == "experiment" && validExperimentNameSDK(config, value.GetName()) || resourceType == "study" && validStudyNameSDK(config, value.GetName()) || resourceType == "trial" && validTrialNameSDK(config, value.GetName())
		if !valid {
			return false
		}
	}
	parts := strings.Split(value.GetName(), "/")
	if len(parts) == 0 || !validExperimentLeaf(parts[len(parts)-1]) || value.GetResourceId() != "" && value.GetResourceId() != parts[len(parts)-1] {
		return false
	}
	value.ResourceId = parts[len(parts)-1]
	return true
}

func validExperimentArtifact(value *artifactv1.ArtifactRef, required bool) bool {
	if value == nil {
		return !required
	}
	return validSHA256Digest(value.GetDigest()) && strings.TrimSpace(value.GetMediaType()) != "" && value.GetSizeBytes() >= 0 && (value.GetIntegrityDigest() == "" || validSHA256Digest(value.GetIntegrityDigest()))
}

func validExperimentMap(values map[string]string, maximum int) bool {
	if len(values) > 128 {
		return false
	}
	for key, value := range values {
		if strings.TrimSpace(key) == "" || len(key) > 128 || len(value) > maximum || hasControlCharacters(key) || strings.ContainsRune(value, '\x00') {
			return false
		}
	}
	return true
}

func validExperimentUpdateMask(paths []string) bool {
	if len(paths) == 0 || len(paths) > 4 {
		return false
	}
	allowed := map[string]bool{"display_name": true, "labels": true, "annotations": true, "policy_classification": true}
	for _, path := range paths {
		if !allowed[path] {
			return false
		}
	}
	return true
}

func validExperimentReason(value string) bool {
	if value == "" || len(value) > 128 || value != strings.ToUpper(value) {
		return false
	}
	for index, character := range value {
		if character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || index > 0 && character == '_' {
			continue
		}
		return false
	}
	return true
}

func normalizeExperimentRPCError(err error, fallback string) error {
	if err != nil {
		return normalizeError(err)
	}
	return protocolDataLoss(fallback)
}

func validateExperimentMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command proto.Message
	switch typed := request.(type) {
	case *internalexperimentv1.CreateExperimentRequest:
		command = cloneGenerated(typed.GetCommand())
	case *internalexperimentv1.UpdateExperimentRequest:
		command = cloneGenerated(typed.GetCommand())
	case *internalexperimentv1.TransitionExperimentRequest:
		command = cloneGenerated(typed.GetCommand())
	case *internalexperimentv1.CreateStudyRequest:
		command = cloneGenerated(typed.GetCommand())
	case *internalexperimentv1.TransitionStudyRequest:
		command = cloneGenerated(typed.GetCommand())
	case *internalexperimentv1.CreateTrialRequest:
		command = cloneGenerated(typed.GetCommand())
	case *internalexperimentv1.TransitionTrialRequest:
		command = cloneGenerated(typed.GetCommand())
	case *internalexperimentv1.CompleteTrialRequest:
		command = cloneGenerated(typed.GetCommand())
	default:
		return false
	}
	if command == nil {
		return false
	}
	reflected := command.ProtoReflect()
	field := reflected.Descriptor().Fields().ByName("context")
	if field == nil || !reflected.Has(field) {
		return false
	}
	context, _ := reflected.Get(field).Message().Interface().(*commonv1.CommandContext)
	reflected.Clear(field)
	digest, err := deterministicDigest(command)
	return err == nil && validRetryContext(context, metadata, config, digest)
}
