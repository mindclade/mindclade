package artifacts

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"regexp"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	objectstorage "github.com/mindclade/mindclade/libs/go/storage"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
)

var aliasPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)

type Server struct {
	internalartifactv1.UnimplementedArtifactServiceServer
	repository ServiceRepository
	transfer   TransferRepository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository ServiceRepository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("artifact server requires repository, identity resolver, and pagination codec")
	}
	transfer, _ := repository.(TransferRepository)
	return &Server{repository: repository, transfer: transfer, identities: identities, pages: pages, clock: realClock{}}, nil
}

func (s *Server) withClock(clock Clock) *Server {
	if clock != nil {
		s.clock = clock
	}
	return s
}

func (s *Server) identity(ctx context.Context) (Identity, error) {
	identity, err := s.identities.Resolve(ctx)
	if err != nil {
		return Identity{}, rpcError(err)
	}
	if err = validateIdentity(identity); err != nil {
		return Identity{}, rpcError(err)
	}
	return identity, nil
}

func (s *Server) GetArtifact(ctx context.Context, request *internalartifactv1.GetArtifactRequest) (*internalartifactv1.GetArtifactResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || (request.GetName() == "") == (request.GetDigest() == "") {
		return nil, rpcError(ErrInvalidArgument)
	}
	digest := request.GetDigest()
	if request.GetName() != "" {
		digest, err = artifactDigestFromName(identity, request.GetName())
		if err != nil {
			return nil, rpcError(err)
		}
	}
	if !validDigest(digest) {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, observedAt, err := s.repository.GetArtifact(ctx, identity, digest)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.GetArtifactResponse{Artifact: sanitizeArtifact(value), ObservedAt: timestamppb.New(observedAt.UTC())}, nil
}

func (s *Server) ListArtifacts(ctx context.Context, request *internalartifactv1.ListArtifactsRequest) (*internalartifactv1.ListArtifactsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != canonicalParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit := int(request.GetPage().GetPageSize())
	if limit == 0 {
		limit = defaultArtifactPageSize
	}
	if limit < 1 || limit > maxArtifactPageSize {
		return nil, rpcError(ErrInvalidArgument)
	}
	state, err := parseArtifactFilter(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	order := strings.TrimSpace(request.GetOrderBy())
	if order == "" {
		order = "create_time desc,digest desc"
	}
	if order != "create_time desc,digest desc" {
		return nil, rpcError(ErrInvalidArgument)
	}
	page := ArtifactPage{Limit: limit, State: state, Filter: strings.TrimSpace(request.GetFilter()), Order: order}
	if token := request.GetPage().GetPageToken(); token != "" {
		cursor, decodeErr := s.pages.Decode(token, identity, page)
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, page.AfterDigest = cursor.AfterTime, cursor.AfterDigest
	}
	values, cursor, readAt, err := s.repository.ListArtifacts(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	nextToken := ""
	if cursor != nil {
		nextToken, err = s.pages.Encode(identity, page, cursor)
		if err != nil {
			return nil, rpcError(err)
		}
	}
	result := make([]*artifactv1.ArtifactRef, 0, len(values))
	for _, value := range values {
		result = append(result, sanitizeArtifact(value))
	}
	return &internalartifactv1.ListArtifactsResponse{Artifacts: result, Page: &commonv1.PageResponse{NextPageToken: nextToken}, ReadTime: timestamppb.New(readAt.UTC())}, nil
}

func (s *Server) ResolveArtifactAlias(ctx context.Context, request *internalartifactv1.ResolveArtifactAliasRequest) (*internalartifactv1.ResolveArtifactAliasResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != canonicalParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	if !aliasPattern.MatchString(request.GetAlias()) {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.ResolveArtifactAlias(ctx, identity, request.GetAlias())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.ResolveArtifactAliasResponse{Artifact: sanitizeArtifact(value)}, nil
}

func (s *Server) CommitArtifact(ctx context.Context, request *internalartifactv1.CommitArtifactRequest) (*internalartifactv1.CommitArtifactResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	if err = validateArtifact(identity, command.GetArtifact(), true); err != nil || !validDigest(command.GetStagingReceiptDigest()) {
		return nil, rpcError(ErrInvalidArgument)
	}
	at := s.clock.Now().UTC().Truncate(time.Microsecond)
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	value, _, err := s.repository.CommitArtifact(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.CommitArtifactResponse{Artifact: sanitizeArtifact(value)}, nil
}

func (s *Server) QuarantineArtifact(ctx context.Context, request *internalartifactv1.QuarantineArtifactRequest) (*internalartifactv1.QuarantineArtifactResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request)
	if err = validateArtifact(identity, command.GetArtifact(), true); err != nil || !reasonCodePattern.MatchString(command.GetReasonCode()) || len(command.GetEvidence()) > 100 {
		return nil, rpcError(ErrInvalidArgument)
	}
	for _, evidence := range command.GetEvidence() {
		if evidence == nil || !validDigest(evidence.GetDigest()) || evidence.GetSubjectDigest() != command.GetArtifact().GetDigest() || evidence.GetEvidenceKind() == "" || len(evidence.GetEvidenceKind()) > 128 || evidence.GetPolicyDigest() != "" && !validDigest(evidence.GetPolicyDigest()) {
			return nil, rpcError(ErrInvalidArgument)
		}
	}
	at := s.clock.Now().UTC().Truncate(time.Microsecond)
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := s.repository.QuarantineArtifact(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.QuarantineArtifactResponse{Operation: clone(operation)}, nil
}

func (s *Server) AcquireArtifactLease(ctx context.Context, request *internalartifactv1.AcquireArtifactLeaseRequest) (*internalartifactv1.AcquireArtifactLeaseResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request)
	if err = validateArtifact(identity, command.GetArtifact(), true); err != nil || command.GetExpireTime() == nil || command.GetExpireTime().CheckValid() != nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	at := s.clock.Now()
	expireAt := command.GetExpireTime().AsTime()
	if !expireAt.After(at) || expireAt.After(at.Add(maxLeaseDuration)) {
		return nil, rpcError(ErrInvalidArgument)
	}
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	lease, _, err := s.repository.AcquireArtifactLease(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.AcquireArtifactLeaseResponse{Lease: clone(lease)}, nil
}

func (s *Server) ReleaseArtifactLease(ctx context.Context, request *internalartifactv1.ReleaseArtifactLeaseRequest) (*internalartifactv1.ReleaseArtifactLeaseResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || request.GetLease() == nil || request.GetEtag() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request)
	lease := command.GetLease()
	wantName := canonicalParent(identity) + "/artifactLeases/" + lease.GetResourceId()
	if lease.GetResourceType() != "artifact_lease" || lease.GetResourceId() == "" || lease.GetTenantId() != identity.TenantID || lease.GetProjectId() != identity.ProjectID || lease.GetName() != wantName || lease.GetEtag() != "" && lease.GetEtag() != command.GetEtag() {
		return nil, rpcError(ErrPermissionDenied)
	}
	at := s.clock.Now()
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	if _, err = s.repository.ReleaseArtifactLease(ctx, identity, command, digest, at); err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.ReleaseArtifactLeaseResponse{}, nil
}

func (s *Server) requireTransfer() (TransferRepository, error) {
	if s.transfer == nil {
		return nil, status.Error(codes.FailedPrecondition, "artifact transfer plane is not configured")
	}
	return s.transfer, nil
}

func (s *Server) BeginArtifactUpload(ctx context.Context, request *internalartifactv1.BeginArtifactUploadRequest) (*internalartifactv1.BeginArtifactUploadResponse, error) {
	transfer, err := s.requireTransfer()
	if err != nil {
		return nil, err
	}
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	at := s.clock.Now().UTC().Truncate(time.Microsecond)
	if request == nil || request.GetContext() == nil || request.GetParent() != canonicalParent(identity) || !aliasPattern.MatchString(request.GetUploadId()) || validateArtifact(identity, request.GetArtifact(), true) != nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request)
	if command.GetExpireTime() == nil {
		command.ExpireTime = timestamppb.New(at.Add(defaultUploadDuration))
	}
	if err = command.GetExpireTime().CheckValid(); err != nil || !command.GetExpireTime().AsTime().After(at) || command.GetExpireTime().AsTime().After(at.Add(maxUploadDuration)) {
		return nil, rpcError(ErrInvalidArgument)
	}
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	value, _, err := transfer.BeginArtifactUpload(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.BeginArtifactUploadResponse{Upload: clone(value)}, nil
}

func (s *Server) UploadArtifactChunk(ctx context.Context, request *internalartifactv1.UploadArtifactChunkRequest) (*internalartifactv1.UploadArtifactChunkResponse, error) {
	transfer, err := s.requireTransfer()
	if err != nil {
		return nil, err
	}
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || request.GetChunkIndex() < 0 || request.GetOffset() < 0 || len(request.GetData()) == 0 || len(request.GetData()) > maxArtifactChunkBytes || !validDigest(request.GetChunkDigest()) || request.GetEtag() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	if _, err = uploadIDFromName(identity, request.GetName()); err != nil {
		return nil, rpcError(err)
	}
	actual := sha256.Sum256(request.GetData())
	if "sha256:"+hex.EncodeToString(actual[:]) != request.GetChunkDigest() {
		return nil, rpcError(ErrIntegrityFailure)
	}
	command := clone(request)
	at := s.clock.Now().UTC().Truncate(time.Microsecond)
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	value, _, err := transfer.UploadArtifactChunk(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.UploadArtifactChunkResponse{Upload: clone(value)}, nil
}

func (s *Server) GetArtifactUpload(ctx context.Context, request *internalartifactv1.GetArtifactUploadRequest) (*internalartifactv1.GetArtifactUploadResponse, error) {
	transfer, err := s.requireTransfer()
	if err != nil {
		return nil, err
	}
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	uploadID, err := uploadIDFromName(identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	value, err := transfer.GetArtifactUpload(ctx, identity, uploadID, s.clock.Now().UTC().Truncate(time.Microsecond))
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.GetArtifactUploadResponse{Upload: clone(value)}, nil
}

func (s *Server) FinalizeArtifactUpload(ctx context.Context, request *internalartifactv1.FinalizeArtifactUploadRequest) (*internalartifactv1.FinalizeArtifactUploadResponse, error) {
	transfer, err := s.requireTransfer()
	if err != nil {
		return nil, err
	}
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	at := s.clock.Now().UTC().Truncate(time.Microsecond)
	if request == nil || request.GetContext() == nil || request.GetEtag() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	if _, err = uploadIDFromName(identity, request.GetName()); err != nil {
		return nil, rpcError(err)
	}
	command := clone(request)
	if command.GetReceiptExpireTime() == nil {
		command.ReceiptExpireTime = timestamppb.New(at.Add(24 * time.Hour))
	}
	if err = command.GetReceiptExpireTime().CheckValid(); err != nil || !command.GetReceiptExpireTime().AsTime().After(at) || command.GetReceiptExpireTime().AsTime().After(at.Add(maxStagingReceiptLifetime)) {
		return nil, rpcError(ErrInvalidArgument)
	}
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	value, receipt, _, err := transfer.FinalizeArtifactUpload(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.FinalizeArtifactUploadResponse{Upload: clone(value), StagingReceipt: clone(receipt)}, nil
}

func (s *Server) AbortArtifactUpload(ctx context.Context, request *internalartifactv1.AbortArtifactUploadRequest) (*internalartifactv1.AbortArtifactUploadResponse, error) {
	transfer, err := s.requireTransfer()
	if err != nil {
		return nil, err
	}
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || request.GetEtag() == "" || !reasonCodePattern.MatchString(request.GetReasonCode()) {
		return nil, rpcError(ErrInvalidArgument)
	}
	if _, err = uploadIDFromName(identity, request.GetName()); err != nil {
		return nil, rpcError(err)
	}
	command := clone(request)
	at := s.clock.Now().UTC().Truncate(time.Microsecond)
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	value, _, err := transfer.AbortArtifactUpload(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.AbortArtifactUploadResponse{Upload: clone(value)}, nil
}

func (s *Server) QuarantineArtifactUpload(ctx context.Context, request *internalartifactv1.QuarantineArtifactUploadRequest) (*internalartifactv1.QuarantineArtifactUploadResponse, error) {
	transfer, err := s.requireTransfer()
	if err != nil {
		return nil, err
	}
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || request.GetEtag() == "" || !reasonCodePattern.MatchString(request.GetReasonCode()) {
		return nil, rpcError(ErrInvalidArgument)
	}
	if _, err = uploadIDFromName(identity, request.GetName()); err != nil {
		return nil, rpcError(err)
	}
	command := clone(request)
	at := s.clock.Now().UTC().Truncate(time.Microsecond)
	digest, err := validateCommandContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, rpcError(err)
	}
	value, _, err := transfer.QuarantineArtifactUpload(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalartifactv1.QuarantineArtifactUploadResponse{Upload: clone(value)}, nil
}

func (s *Server) DownloadArtifact(request *internalartifactv1.DownloadArtifactRequest, stream grpc.ServerStreamingServer[internalartifactv1.DownloadArtifactResponse]) error {
	transfer, err := s.requireTransfer()
	if err != nil {
		return err
	}
	identity, err := s.identity(stream.Context())
	if err != nil {
		return err
	}
	if request == nil || (request.GetName() == "") == (request.GetDigest() == "") || request.GetOffset() < 0 {
		return rpcError(ErrInvalidArgument)
	}
	digest := request.GetDigest()
	if request.GetName() != "" {
		digest, err = artifactDigestFromName(identity, request.GetName())
		if err != nil {
			return rpcError(err)
		}
	}
	if !validDigest(digest) {
		return rpcError(ErrInvalidArgument)
	}
	chunkSize := int(request.GetMaxChunkBytes())
	if chunkSize == 0 {
		chunkSize = defaultDownloadChunk
	}
	if chunkSize < 1 || chunkSize > maxDownloadChunk {
		return rpcError(ErrInvalidArgument)
	}
	artifact, reader, err := transfer.OpenArtifact(stream.Context(), identity, digest, request.GetOffset())
	if err != nil {
		return rpcError(err)
	}
	defer func() { _ = reader.Close() }()
	offset := request.GetOffset()
	buffer := make([]byte, chunkSize)
	for {
		count, readErr := reader.Read(buffer)
		if count > 0 {
			data := append([]byte(nil), buffer[:count]...)
			value := sha256.Sum256(data)
			complete := offset+int64(count) == artifact.GetSizeBytes() && errors.Is(readErr, io.EOF)
			if sendErr := stream.Send(&internalartifactv1.DownloadArtifactResponse{Artifact: sanitizeArtifact(artifact), Offset: offset, Data: data, ChunkDigest: "sha256:" + hex.EncodeToString(value[:]), Complete: complete}); sendErr != nil {
				return rpcError(sendErr)
			}
			offset += int64(count)
		}
		if errors.Is(readErr, io.EOF) {
			if offset != artifact.GetSizeBytes() {
				return rpcError(ErrIntegrityFailure)
			}
			if count == 0 && request.GetOffset() == artifact.GetSizeBytes() {
				empty := sha256.Sum256(nil)
				return stream.Send(&internalartifactv1.DownloadArtifactResponse{Artifact: sanitizeArtifact(artifact), Offset: offset, ChunkDigest: "sha256:" + hex.EncodeToString(empty[:]), Complete: true})
			}
			return nil
		}
		if readErr != nil {
			return rpcError(readErr)
		}
	}
}

func parseArtifactFilter(filter string) (string, error) {
	switch strings.TrimSpace(filter) {
	case "":
		return "", nil
	case `state = "COMMITTED"`:
		return "COMMITTED", nil
	case `state = "QUARANTINED"`:
		return "QUARANTINED", nil
	default:
		return "", ErrInvalidArgument
	}
}

func rpcError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "artifact request cancelled")
	case errors.Is(err, context.DeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, "artifact request deadline exceeded")
	case errors.Is(err, ErrUnauthenticated):
		return status.Error(codes.Unauthenticated, "authenticated identity is required")
	case errors.Is(err, ErrPermissionDenied):
		return status.Error(codes.PermissionDenied, "artifact resource is outside the authenticated scope")
	case errors.Is(err, ErrInvalidArgument), errors.Is(err, ErrPageToken):
		return status.Error(codes.InvalidArgument, "invalid artifact request")
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, "artifact resource not found")
	case errors.Is(err, ErrConflict):
		return status.Error(codes.AlreadyExists, "artifact digest metadata conflicts with existing content")
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrRevisionConflict):
		return status.Error(codes.Aborted, "artifact command concurrency conflict")
	case errors.Is(err, ErrChunkConflict):
		return status.Error(codes.Aborted, "artifact chunk conflicts with durable upload progress")
	case errors.Is(err, ErrIntegrityFailure), errors.Is(err, objectstorage.ErrDigestMismatch), errors.Is(err, objectstorage.ErrSizeMismatch), errors.Is(err, objectstorage.ErrGenerationMismatch):
		return status.Error(codes.DataLoss, "artifact transfer integrity verification failed")
	case errors.Is(err, objectstorage.ErrStorageUnavailable):
		return status.Error(codes.Unavailable, "artifact object storage is unavailable")
	case errors.Is(err, ErrStagingUnverified), errors.Is(err, ErrInvalidTransition), errors.Is(err, ErrUploadExpired):
		return status.Error(codes.FailedPrecondition, "artifact command precondition failed")
	default:
		return status.Error(codes.Internal, "artifact service failed")
	}
}
