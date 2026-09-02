package main

import (
	"context"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	gcppubsub "cloud.google.com/go/pubsub/v2"
	_ "github.com/jackc/pgx/v5/stdlib"

	adminapp "github.com/mindclade/mindclade/services/control_plane/internal/admin"
	agentsapp "github.com/mindclade/mindclade/services/control_plane/internal/agents"
	artifactsapp "github.com/mindclade/mindclade/services/control_plane/internal/artifacts"
	datasetsapp "github.com/mindclade/mindclade/services/control_plane/internal/datasets"
	evaluationsapp "github.com/mindclade/mindclade/services/control_plane/internal/evaluations"
	experimentsapp "github.com/mindclade/mindclade/services/control_plane/internal/experiments"
	inferenceapp "github.com/mindclade/mindclade/services/control_plane/internal/inference"
	jobsapp "github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	modelsapp "github.com/mindclade/mindclade/services/control_plane/internal/models"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/eventprojection"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/inbox"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/outbox"
	objectstorage "github.com/mindclade/mindclade/services/control_plane/internal/platform/storage"
	policiesapp "github.com/mindclade/mindclade/services/control_plane/internal/policies"
	trainingapp "github.com/mindclade/mindclade/services/control_plane/internal/training"
	workflowsapp "github.com/mindclade/mindclade/services/control_plane/internal/workflows"
)

func main() {
	ctx, cancelStartup := context.WithTimeout(context.Background(), 20*time.Second)
	resources, err := newProductionResources(ctx)
	if err != nil {
		cancelStartup()
		slog.Error("control plane dependencies are not ready", "error", err)
		os.Exit(1)
	}

	grpcAddress := valueOrDefault(os.Getenv("MINDCLADE_GRPC_ADDR"), "127.0.0.1:8081")
	httpAddress := valueOrDefault(os.Getenv("MINDCLADE_HTTP_ADDR"), "127.0.0.1:8080")
	server, err := newRuntimeWithAuthorizer(
		ctx,
		grpcAddress,
		httpAddress,
		resources.authorizer,
		runtimeDependencies{
			Public:     resources.training,
			Ready:      resources.training.Ready,
			Admin:      resources.admin,
			Agent:      resources.agents,
			Artifact:   resources.artifacts,
			Dataset:    resources.datasets,
			Evaluation: resources.evaluations,
			Experiment: resources.experiments,
			Inference:  resources.inference,
			Operation:  resources.training.InternalOperationServer(),
			Job:        resources.training.InternalJobServer(),
			Run:        resources.training.InternalRunServer(),
			Model:      resources.models,
			Policy:     resources.policies,
			Training:   resources.training.InternalTrainingServer(),
			Workflow:   resources.workflows,
			Approval:   resources.approvals,
		},
	)
	cancelStartup()
	if err != nil {
		resources.close()
		slog.Error("control plane setup failed", "error", err)
		os.Exit(1)
	}
	defer resources.close()
	signals, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	type runtimeResult struct {
		component string
		err       error
	}
	runContext, cancelRun := context.WithCancel(signals)
	defer cancelRun()
	failed := make(chan runtimeResult, 4)
	go func() { failed <- runtimeResult{component: "grpc/http server", err: server.serve()} }()
	go func() {
		failed <- runtimeResult{component: "outbox dispatcher", err: resources.dispatchOutbox(runContext)}
	}()
	go func() { failed <- runtimeResult{component: "job subscriber", err: resources.consumeJobs(runContext)} }()
	go func() {
		failed <- runtimeResult{component: "event audit projection subscriber", err: resources.consumeEventAudit(runContext)}
	}()
	completed := 0
	select {
	case <-signals.Done():
	case result := <-failed:
		completed = 1
		if result.err != nil {
			slog.Error("control plane component stopped unexpectedly", "component", result.component, "error", result.err)
		}
	}
	cancelRun()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := server.shutdown(ctx); err != nil && !errors.Is(err, context.Canceled) {
		slog.Error("control plane shutdown failed", "error", err)
	}
	for completed < cap(failed) {
		select {
		case result := <-failed:
			completed++
			if result.err != nil {
				slog.Warn("control plane component failed during shutdown", "component", result.component, "error", result.err)
			}
		case <-ctx.Done():
			slog.Error("control plane components did not stop before shutdown deadline", "remaining", cap(failed)-completed)
			return
		}
	}
}

type productionResources struct {
	db            *sql.DB
	pubsubClient  *gcppubsub.Client
	publisher     *outbox.PubSubPublisher
	jobConsumer   *inbox.PubSubConsumer
	auditConsumer *inbox.PubSubConsumer
	dispatcher    outbox.Dispatcher
	tenantIDs     []string
	authorizer    bearerAuthorizer
	admin         *adminapp.Server
	agents        *agentsapp.Server
	training      *publicTrainingAdapter
	artifacts     *artifactsapp.Server
	datasets      *datasetsapp.Server
	evaluations   *evaluationsapp.Server
	experiments   *experimentsapp.Server
	inference     *inferenceapp.Server
	models        *modelsapp.Server
	policies      *policiesapp.Server
	workflows     *workflowsapp.Server
	approvals     *workflowsapp.ApprovalServer
	objectStore   *objectstorage.GCSObjectStore
}

type artifactIdentityResolver struct{}

type adminIdentityResolver struct{}

type agentIdentityResolver struct{}

func (agentIdentityResolver) Resolve(ctx context.Context) (agentsapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return agentsapp.Identity{}, agentsapp.ErrUnauthenticated
	}
	return agentsapp.Identity{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal,
		WorkerID: identity.WorkerID, LeaseToken: identity.LeaseToken, Roles: applicationRoles(ctx),
	}, nil
}

func (adminIdentityResolver) Resolve(ctx context.Context) (adminapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return adminapp.Identity{}, adminapp.ErrUnauthenticated
	}
	return adminapp.Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}, nil
}

type policyIdentityResolver struct{}

func (policyIdentityResolver) Resolve(ctx context.Context) (policiesapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return policiesapp.Identity{}, policiesapp.ErrUnauthenticated
	}
	return policiesapp.Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}, nil
}

func (artifactIdentityResolver) Resolve(ctx context.Context) (artifactsapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return artifactsapp.Identity{}, artifactsapp.ErrUnauthenticated
	}
	return artifactsapp.Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}, nil
}

type datasetIdentityResolver struct{}

func (datasetIdentityResolver) Resolve(ctx context.Context) (datasetsapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return datasetsapp.Identity{}, datasetsapp.ErrUnauthenticated
	}
	return datasetsapp.Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}, nil
}

type modelIdentityResolver struct{}

func (modelIdentityResolver) Resolve(ctx context.Context) (modelsapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return modelsapp.Identity{}, modelsapp.ErrUnauthenticated
	}
	return modelsapp.Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}, nil
}

type evaluationIdentityResolver struct{}

type experimentIdentityResolver struct{}

func (experimentIdentityResolver) Resolve(ctx context.Context) (experimentsapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return experimentsapp.Identity{}, experimentsapp.ErrUnauthenticated
	}
	return experimentsapp.Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}, nil
}

func (evaluationIdentityResolver) Resolve(ctx context.Context) (evaluationsapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return evaluationsapp.Identity{}, evaluationsapp.ErrUnauthenticated
	}
	return evaluationsapp.Identity{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal,
		WorkerID: identity.WorkerID, LeaseToken: identity.LeaseToken,
	}, nil
}

type inferenceIdentityResolver struct{}

func (inferenceIdentityResolver) Resolve(ctx context.Context) (inferenceapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return inferenceapp.Identity{}, inferenceapp.ErrUnauthenticated
	}
	return inferenceapp.Identity{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal,
		WorkerID: identity.WorkerID, LeaseToken: identity.LeaseToken,
	}, nil
}

type workflowIdentityResolver struct{}

func (workflowIdentityResolver) Resolve(ctx context.Context) (workflowsapp.Identity, error) {
	identity, err := (metadataIdentityResolver{}).Resolve(ctx)
	if err != nil {
		return workflowsapp.Identity{}, workflowsapp.ErrUnauthenticated
	}
	return workflowsapp.Identity{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal,
		WorkerID: identity.WorkerID, LeaseToken: identity.LeaseToken, Roles: applicationRoles(ctx),
	}, nil
}

func staticIdentityClaims(runtimeEnvironment string) (verifiedIdentityClaims, error) {
	claims := verifiedIdentityClaims{
		tenantID:    os.Getenv("MINDCLADE_AUTH_TENANT_ID"),
		projectID:   os.Getenv("MINDCLADE_AUTH_PROJECT_ID"),
		principalID: os.Getenv("MINDCLADE_AUTH_PRINCIPAL_ID"),
		workerID:    os.Getenv("MINDCLADE_AUTH_WORKER_ID"),
		leaseToken:  os.Getenv("MINDCLADE_AUTH_LEASE_TOKEN"),
	}
	configuredRoles, err := requiredIdentityList("MINDCLADE_AUTH_ROLES")
	if err != nil {
		return verifiedIdentityClaims{}, err
	}
	claims.roles = make(map[string]struct{}, len(configuredRoles))
	for _, role := range configuredRoles {
		if !supportedAuthorizationRole(role) {
			return verifiedIdentityClaims{}, fmt.Errorf("MINDCLADE_AUTH_ROLES contains unsupported role %q", role)
		}
		claims.roles[role] = struct{}{}
	}
	for name, value := range map[string]string{
		"MINDCLADE_AUTH_TENANT_ID":    claims.tenantID,
		"MINDCLADE_AUTH_PROJECT_ID":   claims.projectID,
		"MINDCLADE_AUTH_PRINCIPAL_ID": claims.principalID,
	} {
		if !validConfiguredIdentity(value) {
			return verifiedIdentityClaims{}, fmt.Errorf("%s must be a bounded identity", name)
		}
	}
	if claims.workerID != "" && !validConfiguredIdentity(claims.workerID) {
		return verifiedIdentityClaims{}, errors.New("MINDCLADE_AUTH_WORKER_ID must be a bounded identity")
	}
	if claims.leaseToken != "" {
		if runtimeEnvironment != "local" && runtimeEnvironment != "test" {
			return verifiedIdentityClaims{}, errors.New("MINDCLADE_AUTH_LEASE_TOKEN is a local/test-only fixture; production workers must use issued lease credentials")
		}
		if len(claims.leaseToken) < 32 {
			return verifiedIdentityClaims{}, errors.New("MINDCLADE_AUTH_LEASE_TOKEN must contain at least 32 characters")
		}
	}
	return claims, nil
}

func mappedTenantIDs(subjects map[string]verifiedIdentityClaims) []string {
	unique := make(map[string]struct{}, len(subjects))
	for _, claims := range subjects {
		unique[claims.tenantID] = struct{}{}
	}
	result := make([]string, 0, len(unique))
	for tenantID := range unique {
		result = append(result, tenantID)
	}
	sort.Strings(result)
	return result
}

func newProductionResources(ctx context.Context) (*productionResources, error) {
	databaseURL, err := requiredEnvironment("MINDCLADE_DATABASE_URL")
	if err != nil {
		return nil, err
	}
	var authorizer bearerAuthorizer
	var authorizedTenantIDs []string
	runtimeEnvironment := valueOrDefault(os.Getenv("MINDCLADE_ENVIRONMENT"), "production")
	if runtimeEnvironment != "local" && runtimeEnvironment != "test" && runtimeEnvironment != "development" && runtimeEnvironment != "staging" && runtimeEnvironment != "production" {
		return nil, fmt.Errorf("MINDCLADE_ENVIRONMENT %q is unsupported", runtimeEnvironment)
	}
	switch authMode := valueOrDefault(os.Getenv("MINDCLADE_AUTH_MODE"), "google-id-token"); authMode {
	case "google-id-token":
		audience, audienceErr := requiredEnvironment("MINDCLADE_AUTH_AUDIENCE")
		if audienceErr != nil {
			return nil, audienceErr
		}
		rawMappings, mappingsErr := requiredEnvironment("MINDCLADE_AUTH_SUBJECT_MAPPINGS")
		if mappingsErr != nil {
			return nil, mappingsErr
		}
		subjects, mappingsErr := parseSubjectMappings(rawMappings)
		if mappingsErr != nil {
			return nil, fmt.Errorf("MINDCLADE_AUTH_SUBJECT_MAPPINGS: %w", mappingsErr)
		}
		verifier, verifierErr := newGoogleIDTokenVerifier(audience, subjects)
		if verifierErr != nil {
			return nil, verifierErr
		}
		authorizer.verify = verifier
		authorizedTenantIDs = mappedTenantIDs(subjects)
	case "static":
		if (runtimeEnvironment != "local" && runtimeEnvironment != "test") || os.Getenv("MINDCLADE_ALLOW_STATIC_AUTH_FOR_TESTING") != "true" {
			return nil, errors.New("static authentication is restricted to an explicitly enabled local/test environment")
		}
		bearerToken, tokenErr := requiredSecret("MINDCLADE_BEARER_TOKEN", 32)
		if tokenErr != nil {
			return nil, tokenErr
		}
		claims, claimsErr := staticIdentityClaims(runtimeEnvironment)
		if claimsErr != nil {
			return nil, claimsErr
		}
		authorizer.token, authorizer.claims = bearerToken, claims
		authorizedTenantIDs = []string{claims.tenantID}
	default:
		return nil, fmt.Errorf("MINDCLADE_AUTH_MODE %q is unsupported", authMode)
	}
	pageKeyEncoded, err := requiredSecret("MINDCLADE_PAGE_TOKEN_HMAC_KEY_B64", 43)
	if err != nil {
		return nil, err
	}
	pageKey, err := base64.RawStdEncoding.DecodeString(pageKeyEncoded)
	if err != nil {
		pageKey, err = base64.StdEncoding.DecodeString(pageKeyEncoded)
	}
	if err != nil || len(pageKey) < 32 {
		return nil, errors.New("MINDCLADE_PAGE_TOKEN_HMAC_KEY_B64 must encode at least 32 random bytes")
	}
	pages, err := trainingapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	runPages, err := jobsapp.NewRunPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	artifactPages, err := artifactsapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	datasetPages, err := datasetsapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	modelPages, err := modelsapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	evaluationPages, err := evaluationsapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	experimentPages, err := experimentsapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	policyPages, err := policiesapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	adminPages, err := adminapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	workflowPages, err := workflowsapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	agentPages, err := agentsapp.NewPageTokenCodec(pageKey)
	if err != nil {
		return nil, err
	}
	inferenceCursorKey, err := requiredBase64Key("MINDCLADE_INFERENCE_CURSOR_HMAC_KEY_B64", 32)
	if err != nil {
		return nil, err
	}
	inferenceCursors, err := inferenceapp.NewCursorCodec(inferenceCursorKey, time.Hour)
	zeroBytes(inferenceCursorKey)
	if err != nil {
		return nil, err
	}
	leaseKeyID, err := requiredEnvironment("MINDCLADE_LEASE_TOKEN_ACTIVE_KEY_ID")
	if err != nil {
		return nil, err
	}
	if !validConfiguredIdentity(leaseKeyID) {
		return nil, errors.New("MINDCLADE_LEASE_TOKEN_ACTIVE_KEY_ID must be a bounded key identifier")
	}
	leaseKeys, err := requiredHMACKeyRing("MINDCLADE_LEASE_TOKEN_HMAC_KEYS_JSON", leaseKeyID)
	if err != nil {
		return nil, err
	}
	leaseTokens, err := jobsapp.NewHMACLeaseTokenIssuer(leaseKeyID, leaseKeys)
	zeroKeyRing(leaseKeys)
	if err != nil {
		return nil, fmt.Errorf("configure lease token issuer: %w", err)
	}

	db, err := sql.Open("pgx", databaseURL)
	if err != nil {
		return nil, fmt.Errorf("open PostgreSQL: %w", err)
	}
	db.SetConnMaxLifetime(30 * time.Minute)
	db.SetConnMaxIdleTime(5 * time.Minute)
	db.SetMaxOpenConns(40)
	db.SetMaxIdleConns(10)
	if err = verifyDatabase(ctx, db); err != nil {
		_ = db.Close()
		return nil, err
	}

	projectID, err := requiredEnvironment("MINDCLADE_GCP_PROJECT_ID")
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	topic, err := requiredEnvironment("MINDCLADE_PUBSUB_EVENT_TOPIC")
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	jobSubscription, err := requiredEnvironment("MINDCLADE_PUBSUB_JOB_SUBSCRIPTION")
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	auditSubscription, err := requiredEnvironment("MINDCLADE_PUBSUB_EVENT_AUDIT_SUBSCRIPTION")
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	if auditSubscription == jobSubscription {
		_ = db.Close()
		return nil, errors.New("job and event-audit consumers require distinct Pub/Sub subscriptions")
	}
	quarantineTenantID, err := requiredEnvironment("MINDCLADE_QUARANTINE_TENANT_ID")
	if err != nil || !validConfiguredIdentity(quarantineTenantID) {
		_ = db.Close()
		if err != nil {
			return nil, err
		}
		return nil, errors.New("MINDCLADE_QUARANTINE_TENANT_ID must be a bounded identity")
	}
	pubsubClient, err := gcppubsub.NewClient(ctx, projectID)
	if err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("create Pub/Sub client: %w", err)
	}
	publisher, err := outbox.NewPubSubPublisher(pubsubClient, topic)
	if err != nil {
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	jobConsumer, err := inbox.NewPubSubConsumer(pubsubClient, jobSubscription, inbox.Processor{
		DB: db, Consumer: "control-plane-job-requested-v1", Handler: jobsapp.JobRequestedHandler{},
		AcceptedEvents:     map[string]uint32{"mindclade.events.job.v1.JobRequested": 1},
		QuarantineTenantID: quarantineTenantID,
	})
	if err != nil {
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, fmt.Errorf("configure JobRequested subscriber: %w", err)
	}
	jobConsumer.OnError = func(_ context.Context, eventErr error) {
		slog.Warn("JobRequested delivery was not processed normally", "error", eventErr)
	}
	projectedEvents, err := eventprojection.AcceptedEvents()
	if err != nil {
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, fmt.Errorf("configure event audit projection registry: %w", err)
	}
	auditConsumer, err := inbox.NewPubSubConsumer(pubsubClient, auditSubscription, inbox.Processor{
		DB: db, Consumer: eventprojection.ConsumerName, Handler: eventprojection.Handler{},
		AcceptedEvents: projectedEvents, QuarantineTenantID: quarantineTenantID,
	})
	if err != nil {
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, fmt.Errorf("configure event audit projection subscriber: %w", err)
	}
	auditConsumer.OnError = func(_ context.Context, eventErr error) {
		slog.Warn("event audit projection delivery was not processed normally", "error", eventErr)
	}
	artifactBucket, err := requiredEnvironment("MINDCLADE_GCS_ARTIFACT_BUCKET")
	if err != nil {
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	objectStore, err := objectstorage.NewGCSObjectStore(ctx, objectstorage.GCSConfig{
		Bucket: artifactBucket, Prefix: valueOrDefault(os.Getenv("MINDCLADE_GCS_ARTIFACT_PREFIX"), "mindclade/artifacts/v1"),
	})
	if err != nil {
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	if err = objectStore.Ready(ctx); err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, fmt.Errorf("verify artifact object storage: %w", err)
	}

	identities := metadataIdentityResolver{}
	schedulerRepository := jobsapp.SQLRepository{DB: db}
	repository := trainingapp.SQLRepository{DB: db, Pagination: pages, Events: trainingapp.GeneratedEventFactory{}}
	application, err := trainingapp.NewServer(repository, identities, pages, 250*time.Millisecond)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	jobServer, err := jobsapp.NewJobServer(schedulerRepository, identities, runPages)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	runServer, err := jobsapp.NewRunServer(schedulerRepository, identities, runPages, leaseTokens)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	ready := func(readyCtx context.Context) error { return verifyDatabase(readyCtx, db) }
	publicTraining, err := newPublicTrainingAdapter(application, jobServer, runServer, identities, ready)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	staging, err := artifactsapp.NewStagingVerifier(artifactsapp.SQLGCSStagingReceiptStore{DB: db, Objects: objectStore})
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	artifactServer, err := artifactsapp.NewServer(
		artifactsapp.SQLRepository{DB: db, Staging: staging, Events: artifactsapp.GeneratedEventFactory{}, Objects: objectStore},
		artifactIdentityResolver{}, artifactPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	datasetServer, err := datasetsapp.NewServer(
		datasetsapp.SQLRepository{DB: db, Pagination: datasetPages, Events: datasetsapp.GeneratedEventFactory{}},
		datasetIdentityResolver{}, datasetPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	modelServer, err := modelsapp.NewServer(
		modelsapp.SQLRepository{DB: db, Pagination: modelPages, Events: modelsapp.GeneratedEventFactory{}},
		modelIdentityResolver{}, modelPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	evaluationServer, err := evaluationsapp.NewServer(
		evaluationsapp.SQLRepository{DB: db, Pagination: evaluationPages, Events: evaluationsapp.GeneratedEventFactory{}},
		evaluationIdentityResolver{}, evaluationPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	experimentServer, err := experimentsapp.NewServer(
		experimentsapp.SQLRepository{DB: db, Pagination: experimentPages, Events: experimentsapp.GeneratedEventFactory{}},
		experimentIdentityResolver{}, experimentPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	inferenceServer, err := inferenceapp.NewServer(
		inferenceapp.SQLRepository{DB: db, Events: inferenceapp.GeneratedEventFactory{}},
		inferenceIdentityResolver{}, inferenceCursors, 250*time.Millisecond, 10*time.Second,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	workflowServer, approvalServer, err := workflowsapp.NewServer(
		workflowsapp.SQLRepository{DB: db, Pagination: workflowPages, Events: workflowsapp.GeneratedEventFactory{}},
		workflowIdentityResolver{}, workflowPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	agentServer, err := agentsapp.NewServer(
		agentsapp.SQLRepository{DB: db, Pagination: agentPages, Events: agentsapp.GeneratedEventFactory{}},
		agentIdentityResolver{}, agentPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	policyServer, err := policiesapp.NewServer(
		policiesapp.SQLRepository{DB: db, Pagination: policyPages, Events: policiesapp.GeneratedEventFactory{}, Evaluator: policiesapp.DenyAllEvaluator{ReasonCode: "POLICY_ENGINE_UNAVAILABLE"}},
		policyIdentityResolver{}, policyPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	auditExporterConfigured, err := optionalBooleanEnvironment("MINDCLADE_AUDIT_EXPORTER_CONFIGURED", false)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	adminServer, err := adminapp.NewServer(
		adminapp.SQLRepository{DB: db, Pagination: adminPages, Events: adminapp.GeneratedEventFactory{}, ExporterConfigured: auditExporterConfigured},
		adminIdentityResolver{}, adminPages,
	)
	if err != nil {
		_ = objectStore.Close()
		publisher.Close()
		_ = pubsubClient.Close()
		_ = db.Close()
		return nil, err
	}
	outboxTenantIDs := authorizedTenantIDs
	if configured := os.Getenv("MINDCLADE_OUTBOX_TENANT_IDS"); configured != "" {
		outboxTenantIDs, err = parseIdentityList(configured)
		if err != nil {
			_ = objectStore.Close()
			publisher.Close()
			_ = pubsubClient.Close()
			_ = db.Close()
			return nil, fmt.Errorf("MINDCLADE_OUTBOX_TENANT_IDS: %w", err)
		}
	}
	return &productionResources{
		db: db, pubsubClient: pubsubClient, publisher: publisher, jobConsumer: jobConsumer, auditConsumer: auditConsumer,
		dispatcher: outbox.Dispatcher{
			Store: outbox.SQLStore{DB: db}, Publisher: publisher, ClaimTTL: 30 * time.Second,
		},
		tenantIDs: outboxTenantIDs, authorizer: authorizer, training: publicTraining,
		agents: agentServer, artifacts: artifactServer, datasets: datasetServer, evaluations: evaluationServer, experiments: experimentServer, inference: inferenceServer,
		models: modelServer, policies: policyServer, admin: adminServer, workflows: workflowServer, approvals: approvalServer, objectStore: objectStore,
	}, nil
}

func verifyDatabase(ctx context.Context, db *sql.DB) error {
	if err := db.PingContext(ctx); err != nil {
		return fmt.Errorf("ping PostgreSQL: %w", err)
	}
	var superuser, bypassRLS, trainingTable, artifactTable, stagingReceiptTable bool
	var datasetTable, datasetReleaseTable, modelTable, modelReleaseTable, dataModelReceiptTable bool
	var evaluationRunTable, evaluationResultTable, inferenceRequestTable, evaluationInferenceReceiptTable bool
	var workflowDefinitionTable, approvalRequestTable, agentDefinitionTable, workflowAgentReceiptTable bool
	var usePolicyTable, administrativeProjectTable, administrativeAuditTable, policyAdminReceiptTable bool
	var eventAuditProjectionTable, eventAuditProjectionHeadTable bool
	var experimentTable, experimentStudyTable, experimentTrialTable, experimentReceiptTable bool
	var forcedFoundationRLS, forcedDataModelRLS, forcedEvaluationInferenceRLS, forcedWorkflowAgentRLS, forcedPolicyAdminRLS, forcedEventProjectionRLS, forcedExperimentRLS int
	if err := db.QueryRowContext(ctx, `
SELECT role.rolsuper, role.rolbypassrls,
       to_regclass('public.training_runs') IS NOT NULL,
       to_regclass('public.artifact_catalog_entries') IS NOT NULL,
	   to_regclass('public.artifact_staging_receipts') IS NOT NULL,
	   to_regclass('public.datasets') IS NOT NULL,
	   to_regclass('public.dataset_releases') IS NOT NULL,
	   to_regclass('public.models') IS NOT NULL,
	   to_regclass('public.model_releases') IS NOT NULL,
	   to_regclass('public.data_model_command_receipts') IS NOT NULL,
	   to_regclass('public.evaluation_runs') IS NOT NULL,
	   to_regclass('public.evaluation_results') IS NOT NULL,
	   to_regclass('public.inference_requests') IS NOT NULL,
	   to_regclass('public.evaluation_inference_command_receipts') IS NOT NULL,
	   to_regclass('public.workflow_definitions') IS NOT NULL,
	   to_regclass('public.approval_requests') IS NOT NULL,
	   to_regclass('public.agent_definitions') IS NOT NULL,
	   to_regclass('public.workflow_agent_command_receipts') IS NOT NULL,
	   to_regclass('public.use_policies') IS NOT NULL,
	   to_regclass('public.administrative_projects') IS NOT NULL,
	   to_regclass('public.administrative_audit_records') IS NOT NULL,
	   to_regclass('public.policy_admin_command_receipts') IS NOT NULL,
	   to_regclass('public.event_audit_projection') IS NOT NULL,
	   to_regclass('public.event_audit_projection_heads') IS NOT NULL,
	   to_regclass('public.experiments') IS NOT NULL,
	   to_regclass('public.experiment_studies') IS NOT NULL,
	   to_regclass('public.experiment_trials') IS NOT NULL,
	   to_regclass('public.experiment_command_receipts') IS NOT NULL,
	   (SELECT count(*) FROM pg_class AS isolated WHERE isolated.relnamespace = 'public'::regnamespace AND isolated.relname = ANY(ARRAY[
	     'artifact_references','resource_references','error_details','error_field_violations','error_precondition_violations',
	     'operations','operation_revisions','training_progress_snapshots','training_runs','training_run_labels','training_checkpoints',
	     'jobs','runs','run_output_refs','attempts','attempt_output_refs','attempt_completion_history','run_command_receipts',
	     'run_command_receipt_attempts','artifacts','idempotency_records','audit_events','outbox_messages','inbox_messages',
	     'inbox_delivery_failures','dead_letter_messages','dead_letter_replay_receipts','artifact_staging_receipts','artifact_upload_sessions','artifact_upload_chunks',
	     'artifact_catalog_entries','artifact_aliases','artifact_quarantine_evidence','artifact_leases','artifact_operations','artifact_command_receipts'
	   ]) AND isolated.relrowsecurity AND isolated.relforcerowsecurity),
	   (SELECT count(*) FROM pg_class AS isolated WHERE isolated.relnamespace = 'public'::regnamespace AND isolated.relname = ANY(ARRAY[
	     'datasets','dataset_labels','dataset_annotations','dataset_releases',
	     'dataset_release_qualification_evidence','dataset_release_revocation_evidence',
	     'models','model_labels','model_annotations','model_releases',
	     'model_release_evaluation_evidence','model_release_transition_evidence',
	     'data_model_command_receipts'
	   ]) AND isolated.relrowsecurity AND isolated.relforcerowsecurity),
	   (SELECT count(*) FROM pg_class AS isolated WHERE isolated.relnamespace = 'public'::regnamespace AND isolated.relname = ANY(ARRAY[
	     'policy_snapshot_references','authorization_decisions','authorization_decision_policies','authorization_decision_constraints',
	     'evaluation_runs','evaluation_run_datasets','evaluation_run_policies','evaluation_results','evaluation_result_metrics',
	     'evaluation_result_thresholds','evaluation_result_failure_counts','promotion_decisions','promotion_decision_results',
	     'promotion_decision_rules','promotion_decision_exceptions','promotion_exception_approvals','promotion_decision_authorizations',
	     'inference_requests','inference_request_output_kinds','inference_request_policies','inference_results',
	     'inference_result_candidates','inference_result_authorizations','evaluation_inference_command_receipts'
	   ]) AND isolated.relrowsecurity AND isolated.relforcerowsecurity),
	   (SELECT count(*) FROM pg_class AS isolated WHERE isolated.relnamespace = 'public'::regnamespace AND isolated.relname = ANY(ARRAY[
	     'workflow_definitions','workflow_definition_tools','workflow_definition_policies','workflow_runs','workflow_run_active_nodes',
	     'workflow_transition_revisions','workflow_transition_active_nodes','approval_requests','approval_request_input_artifacts',
	     'approval_request_policy_decisions','approval_receipts','approval_receipt_input_artifacts','approval_receipt_consumptions',
	     'agent_definitions','agent_definition_non_goals','agent_definition_tools','agent_definition_policies','agent_runs',
	     'agent_run_policies','agent_steps','agent_step_policy_decisions','agent_step_observations','agent_step_decisions',
	     'agent_decision_evidence','agent_tool_calls','agent_tool_call_approvals','agent_tool_call_inputs','agent_tool_receipts',
	     'agent_tool_receipt_approvals','agent_tool_receipt_outputs','workflow_agent_command_receipts'
	   ]) AND isolated.relrowsecurity AND isolated.relforcerowsecurity),
	   (SELECT count(*) FROM pg_class AS isolated WHERE isolated.relnamespace = 'public'::regnamespace AND isolated.relname = ANY(ARRAY[
	     'use_policies','use_policy_permitted_purposes','use_policy_permitted_capabilities','use_policy_prohibited_capabilities',
	     'use_policy_accepted_classifications','use_policy_approval_requirements','administrative_tenants',
	     'administrative_tenant_policy_snapshots','administrative_tenant_allowed_regions','administrative_tenant_labels',
	     'administrative_tenant_annotations','administrative_projects','administrative_project_policy_snapshots',
	     'administrative_project_labels','administrative_project_annotations','administrative_audit_records','audit_exports',
	     'audit_export_actor_filters','audit_export_action_filters','audit_export_resource_filters','audit_export_result_filters',
	     'audit_export_reason_filters','policy_admin_command_receipts'
	   ]) AND isolated.relrowsecurity AND isolated.relforcerowsecurity),
	   (SELECT count(*) FROM pg_class AS isolated WHERE isolated.relnamespace = 'public'::regnamespace AND isolated.relname = ANY(ARRAY[
	     'event_audit_projection','event_audit_projection_heads'
	   ]) AND isolated.relrowsecurity AND isolated.relforcerowsecurity),
	   (SELECT count(*) FROM pg_class AS isolated WHERE isolated.relnamespace = 'public'::regnamespace AND isolated.relname = ANY(ARRAY[
	     'experiments','experiment_labels','experiment_annotations','experiment_subjects',
	     'experiment_studies','experiment_trials','experiment_trial_evidence','experiment_command_receipts'
	   ]) AND isolated.relrowsecurity AND isolated.relforcerowsecurity)
FROM pg_roles AS role WHERE role.rolname = current_user`).Scan(
		&superuser, &bypassRLS, &trainingTable, &artifactTable, &stagingReceiptTable,
		&datasetTable, &datasetReleaseTable, &modelTable, &modelReleaseTable, &dataModelReceiptTable,
		&evaluationRunTable, &evaluationResultTable, &inferenceRequestTable, &evaluationInferenceReceiptTable,
		&workflowDefinitionTable, &approvalRequestTable, &agentDefinitionTable, &workflowAgentReceiptTable,
		&usePolicyTable, &administrativeProjectTable, &administrativeAuditTable, &policyAdminReceiptTable,
		&eventAuditProjectionTable, &eventAuditProjectionHeadTable,
		&experimentTable, &experimentStudyTable, &experimentTrialTable, &experimentReceiptTable,
		&forcedFoundationRLS, &forcedDataModelRLS, &forcedEvaluationInferenceRLS, &forcedWorkflowAgentRLS, &forcedPolicyAdminRLS, &forcedEventProjectionRLS, &forcedExperimentRLS,
	); err != nil {
		return fmt.Errorf("verify PostgreSQL runtime role: %w", err)
	}
	if superuser || bypassRLS {
		return errors.New("PostgreSQL runtime role must be NOSUPERUSER and NOBYPASSRLS")
	}
	if !trainingTable {
		return errors.New("PostgreSQL migrations are incomplete: training_runs is absent")
	}
	if !artifactTable || !stagingReceiptTable {
		return errors.New("PostgreSQL migrations are incomplete: artifact catalog or staging receipts are absent")
	}
	if forcedFoundationRLS != 36 {
		return fmt.Errorf("PostgreSQL foundation tenant isolation is incomplete: %d/36 tables force RLS", forcedFoundationRLS)
	}
	if !datasetTable || !datasetReleaseTable || !modelTable || !modelReleaseTable || !dataModelReceiptTable {
		return errors.New("PostgreSQL migrations are incomplete: dataset/model lifecycle tables are absent")
	}
	if forcedDataModelRLS != 13 {
		return fmt.Errorf("PostgreSQL dataset/model tenant isolation is incomplete: %d/13 tables force RLS", forcedDataModelRLS)
	}
	if !evaluationRunTable || !evaluationResultTable || !inferenceRequestTable || !evaluationInferenceReceiptTable {
		return errors.New("PostgreSQL migrations are incomplete: evaluation/inference lifecycle tables are absent")
	}
	if forcedEvaluationInferenceRLS != 24 {
		return fmt.Errorf("PostgreSQL evaluation/inference tenant isolation is incomplete: %d/24 tables force RLS", forcedEvaluationInferenceRLS)
	}
	if !workflowDefinitionTable || !approvalRequestTable || !agentDefinitionTable || !workflowAgentReceiptTable {
		return errors.New("PostgreSQL migrations are incomplete: workflow/approval/agent lifecycle tables are absent")
	}
	if forcedWorkflowAgentRLS != 31 {
		return fmt.Errorf("PostgreSQL workflow/agent tenant isolation is incomplete: %d/31 tables force RLS", forcedWorkflowAgentRLS)
	}
	if !usePolicyTable || !administrativeProjectTable || !administrativeAuditTable || !policyAdminReceiptTable {
		return errors.New("PostgreSQL migrations are incomplete: policy/administrative lifecycle tables are absent")
	}
	if forcedPolicyAdminRLS != 23 {
		return fmt.Errorf("PostgreSQL policy/admin tenant isolation is incomplete: %d/23 tables force RLS", forcedPolicyAdminRLS)
	}
	if !eventAuditProjectionTable || !eventAuditProjectionHeadTable {
		return errors.New("PostgreSQL migrations are incomplete: event audit projection tables are absent")
	}
	if forcedEventProjectionRLS != 2 {
		return fmt.Errorf("PostgreSQL event projection tenant isolation is incomplete: %d/2 tables force RLS", forcedEventProjectionRLS)
	}
	if !experimentTable || !experimentStudyTable || !experimentTrialTable || !experimentReceiptTable {
		return errors.New("PostgreSQL migrations are incomplete: experiment lifecycle tables are absent")
	}
	if forcedExperimentRLS != 8 {
		return fmt.Errorf("PostgreSQL experiment tenant isolation is incomplete: %d/8 tables force RLS", forcedExperimentRLS)
	}
	return nil
}

func (r *productionResources) dispatchOutbox(ctx context.Context) error {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		batchFull := false
		for _, tenantID := range r.tenantIDs {
			delivered, err := r.dispatcher.DeliverBatch(ctx, tenantID, 100)
			if err != nil && !errors.Is(err, context.Canceled) {
				slog.Warn("transactional outbox delivery failed", "tenant", tenantID, "error", err)
			}
			batchFull = batchFull || delivered == 100
		}
		if ctx.Err() != nil {
			return nil
		}
		if batchFull {
			continue
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func (r *productionResources) consumeJobs(ctx context.Context) error {
	if r.jobConsumer == nil {
		return errors.New("JobRequested Pub/Sub consumer is not configured")
	}
	err := r.jobConsumer.Receive(ctx)
	if ctx.Err() != nil {
		return nil //nolint:nilerr // Consumer cancellation is the expected coordinated shutdown path.
	}
	if errors.Is(err, context.Canceled) {
		return nil
	}
	return err
}

func (r *productionResources) consumeEventAudit(ctx context.Context) error {
	if r.auditConsumer == nil {
		return errors.New("event audit projection Pub/Sub consumer is not configured")
	}
	err := r.auditConsumer.Receive(ctx)
	if ctx.Err() != nil {
		return nil //nolint:nilerr // Consumer cancellation is the expected coordinated shutdown path.
	}
	if errors.Is(err, context.Canceled) {
		return nil
	}
	return err
}

func (r *productionResources) close() {
	if r.objectStore != nil {
		if err := r.objectStore.Close(); err != nil {
			slog.Warn("close artifact object storage", "error", err)
		}
	}
	if r.publisher != nil {
		r.publisher.Close()
	}
	if r.pubsubClient != nil {
		if err := r.pubsubClient.Close(); err != nil {
			slog.Warn("close Pub/Sub client", "error", err)
		}
	}
	if r.db != nil {
		if err := r.db.Close(); err != nil {
			slog.Warn("close PostgreSQL pool", "error", err)
		}
	}
}

func requiredEnvironment(name string) (string, error) {
	value := os.Getenv(name)
	if value == "" || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
		return "", fmt.Errorf("%s is required and must not contain control characters", name)
	}
	return value, nil
}

func requiredSecret(name string, minimumLength int) (string, error) {
	value, err := requiredEnvironment(name)
	if err != nil {
		return "", err
	}
	if len(value) < minimumLength {
		return "", fmt.Errorf("%s must contain at least %d characters", name, minimumLength)
	}
	return value, nil
}

func requiredBase64Key(name string, minimumBytes int) ([]byte, error) {
	encoded, err := requiredSecret(name, 43)
	if err != nil {
		return nil, err
	}
	var value []byte
	for _, encoding := range []*base64.Encoding{base64.RawStdEncoding, base64.StdEncoding, base64.RawURLEncoding, base64.URLEncoding} {
		value, err = encoding.DecodeString(encoded)
		if err == nil {
			break
		}
	}
	if err != nil || len(value) < minimumBytes {
		zeroBytes(value)
		return nil, fmt.Errorf("%s must encode at least %d random bytes", name, minimumBytes)
	}
	return value, nil
}

func requiredHMACKeyRing(name, activeKeyID string) (map[string][]byte, error) {
	raw, err := requiredSecret(name, 2)
	if err != nil {
		return nil, err
	}
	keys, err := parseHMACKeyRing(raw, activeKeyID)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return keys, nil
}

func requiredIdentityList(name string) ([]string, error) {
	value, err := requiredEnvironment(name)
	if err != nil {
		return nil, err
	}
	result, err := parseIdentityList(value)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return result, nil
}

func valueOrDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func optionalBooleanEnvironment(name string, fallback bool) (bool, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
	}
	if strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
		return false, fmt.Errorf("%s must be a boolean without control characters", name)
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return false, fmt.Errorf("%s must be true or false: %w", name, err)
	}
	return parsed, nil
}
