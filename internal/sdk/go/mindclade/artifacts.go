package mindclade

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const defaultArtifactUploadChunkBytes = 1 << 20

// ArtifactUploadOptions controls the ergonomic transfer workflow. Authoritative
// state and wire values remain generated protobuf messages.
type ArtifactUploadOptions struct {
	UploadID       string
	ChunkBytes     int
	SessionTTL     time.Duration
	ReceiptTTL     time.Duration
	RequestOptions []RequestOption
}

type ArtifactService struct {
	client    *Client
	transport internalartifactv1.ArtifactServiceClient
}

// Resolve converts a mutable alias or digest into the immutable generated
// ArtifactRef observed by the artifact catalog.
func (service *ArtifactService) Resolve(ctx context.Context, value string, options ...RequestOption) (*artifactv1.ArtifactRef, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact alias or digest is required"}
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	if isSHA256Digest(value) {
		response, callErr := service.transport.GetArtifact(
			callContext,
			&internalartifactv1.GetArtifactRequest{Digest: value},
		)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		if response.GetArtifact() == nil {
			return nil, &Error{Code: CodeDataLoss, Message: "artifact catalog returned no artifact"}
		}
		return response.GetArtifact(), nil
	}
	response, callErr := service.transport.ResolveArtifactAlias(
		callContext,
		&internalartifactv1.ResolveArtifactAliasRequest{
			Parent: projectName(service.client.config.TenantID, service.client.config.ProjectID),
			Alias:  value,
		},
	)
	if callErr != nil {
		return nil, normalizeError(callErr)
	}
	if response.GetArtifact() == nil || !isSHA256Digest(response.GetArtifact().GetDigest()) {
		return nil, &Error{Code: CodeDataLoss, Message: "artifact alias did not resolve to immutable content"}
	}
	return response.GetArtifact(), nil
}

// Download writes verified bytes to destination. Partial or corrupt content is
// reported as DataLoss; callers decide whether to discard a partially written
// destination.
func (service *ArtifactService) Download(ctx context.Context, artifact *artifactv1.ArtifactRef, destination io.Writer, options ...RequestOption) error {
	if artifact == nil || !isSHA256Digest(artifact.GetDigest()) {
		return &Error{Code: CodeInvalidArgument, Message: "an immutable sha256 ArtifactRef is required"}
	}
	if destination == nil {
		return &Error{Code: CodeInvalidArgument, Message: "artifact destination is required"}
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return err
	}
	defer cancel()
	stream, err := service.transport.DownloadArtifact(callContext, &internalartifactv1.DownloadArtifactRequest{Digest: artifact.GetDigest(), MaxChunkBytes: defaultArtifactUploadChunkBytes})
	if err != nil {
		return normalizeError(err)
	}
	digest := sha256.New()
	var written int64
	complete := false
	for {
		response, receiveErr := stream.Recv()
		if receiveErr != nil {
			if errors.Is(receiveErr, io.EOF) && complete {
				break
			}
			return normalizeError(receiveErr)
		}
		if response.GetArtifact() == nil || !proto.Equal(response.GetArtifact(), artifact) || response.GetOffset() != written {
			return &Error{Code: CodeDataLoss, Message: "artifact download stream identity or offset changed"}
		}
		chunk := response.GetData()
		chunkDigest := sha256.Sum256(chunk)
		if response.GetChunkDigest() != "sha256:"+hex.EncodeToString(chunkDigest[:]) {
			return &Error{Code: CodeDataLoss, Message: "artifact download chunk digest verification failed"}
		}
		if len(chunk) > 0 {
			count, writeErr := io.MultiWriter(destination, digest).Write(chunk)
			if writeErr != nil {
				return normalizeError(writeErr)
			}
			if count != len(chunk) {
				return &Error{Code: CodeDataLoss, Message: "artifact destination accepted a short write"}
			}
			written += int64(count)
		}
		complete = response.GetComplete()
		if complete {
			break
		}
	}
	if artifact.GetSizeBytes() >= 0 && written != artifact.GetSizeBytes() {
		return &Error{Code: CodeDataLoss, Message: fmt.Sprintf("artifact size mismatch: expected %d, got %d", artifact.GetSizeBytes(), written)}
	}
	actual := "sha256:" + hex.EncodeToString(digest.Sum(nil))
	if actual != artifact.GetDigest() {
		return &Error{Code: CodeDataLoss, Message: "artifact digest verification failed"}
	}
	return nil
}

// Upload transfers caller-known immutable content through generated gRPC
// clients and returns the opaque staging receipt used by CommitArtifact. A
// replay resumes from the server's durable contiguous offset.
func (service *ArtifactService) Upload(
	ctx context.Context,
	artifact *artifactv1.ArtifactRef,
	source io.Reader,
	options ArtifactUploadOptions,
) (*internalartifactv1.ArtifactStagingReceipt, error) {
	if err := validateUploadArtifact(artifact); err != nil || source == nil {
		if err != nil {
			return nil, err
		}
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload source is required"}
	}
	uploadID := strings.TrimSpace(options.UploadID)
	explicitUploadID := uploadID != ""
	if uploadID == "" {
		var err error
		uploadID, err = randomID()
		if err != nil {
			return nil, err
		}
	}
	if !validUploadID(uploadID) {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload ID is invalid"}
	}
	chunkBytes := options.ChunkBytes
	if chunkBytes == 0 {
		chunkBytes = defaultArtifactUploadChunkBytes
	}
	if chunkBytes < 1 || chunkBytes > 4<<20 {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload chunk size must be between 1 byte and 4 MiB"}
	}
	sessionTTL := options.SessionTTL
	if sessionTTL == 0 {
		sessionTTL = 2 * time.Hour
	}
	receiptTTL := options.ReceiptTTL
	if receiptTTL == 0 {
		receiptTTL = 24 * time.Hour
	}
	if sessionTTL <= 0 || sessionTTL > 24*time.Hour || receiptTTL <= 0 || receiptTTL > 7*24*time.Hour {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload or receipt lifetime is outside policy"}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	uploadName := parent + "/artifactUploads/" + uploadID
	var upload *internalartifactv1.ArtifactUploadSession
	if explicitUploadID {
		existing, getErr := service.getUpload(ctx, uploadName, options.RequestOptions...)
		if getErr == nil {
			upload = existing
		} else if !hasErrorCode(getErr, CodeNotFound) {
			return nil, getErr
		}
	}
	if upload == nil {
		beginContext, beginRequest, beginCancel, err := service.client.context(ctx, append(options.RequestOptions, WithIdempotencyKey("artifact-upload:"+uploadID+":begin"))...)
		if err != nil {
			return nil, err
		}
		begin := &internalartifactv1.BeginArtifactUploadRequest{Parent: parent, Artifact: proto.Clone(artifact).(*artifactv1.ArtifactRef), UploadId: uploadID, ExpireTime: timestamppb.New(time.Now().UTC().Add(sessionTTL))}
		digest, digestErr := deterministicDigest(begin)
		if digestErr != nil {
			beginCancel()
			return nil, digestErr
		}
		begin.Context = commandContext(service.client.config, beginContext, beginRequest, digest)
		begun, beginErr := service.transport.BeginArtifactUpload(beginContext, begin)
		beginCancel()
		if beginErr != nil {
			normalized := normalizeError(beginErr)
			if !hasErrorCode(normalized, CodeAlreadyExists) && !hasErrorCode(normalized, CodeAborted) {
				return nil, normalized
			}
			upload, err = service.getUpload(ctx, uploadName, options.RequestOptions...)
			if err != nil {
				return nil, err
			}
		} else {
			upload = begun.GetUpload()
		}
	}
	if upload == nil || upload.GetArtifact() == nil || !proto.Equal(upload.GetArtifact(), artifact) || upload.GetName() == "" {
		return nil, &Error{Code: CodeDataLoss, Message: "artifact upload begin returned an invalid session"}
	}
	if upload.GetState() == internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_FINALIZED {
		if upload.GetStagingReceipt() == nil {
			return nil, &Error{Code: CodeDataLoss, Message: "finalized artifact upload omitted its receipt"}
		}
		return upload.GetStagingReceipt(), nil
	}
	if upload.GetState() != internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN || upload.GetCommittedOffset() < 0 || upload.GetCommittedOffset() > artifact.GetSizeBytes() {
		return nil, &Error{Code: CodeFailedPrecondition, Message: "artifact upload session cannot be resumed"}
	}
	fullDigest := sha256.New()
	if upload.GetCommittedOffset() > 0 {
		if _, copyErr := io.CopyN(fullDigest, source, upload.GetCommittedOffset()); copyErr != nil {
			return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload source is shorter than the durable resume offset", Cause: copyErr}
		}
	}
	offset := upload.GetCommittedOffset()
	buffer := make([]byte, chunkBytes)
	for offset < artifact.GetSizeBytes() {
		remaining := artifact.GetSizeBytes() - offset
		readSize := chunkBytes
		if remaining < int64(readSize) {
			readSize = int(remaining)
		}
		count, readErr := io.ReadFull(source, buffer[:readSize])
		if readErr != nil {
			return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload source ended before declared size", Cause: readErr}
		}
		data := append([]byte(nil), buffer[:count]...)
		chunkDigest := sha256.Sum256(data)
		_, _ = fullDigest.Write(data)
		chunkKey := fmt.Sprintf("artifact-upload:%s:chunk:%d:%x", uploadID, upload.GetNextChunkIndex(), chunkDigest)
		chunkContext, chunkRequest, chunkCancel, contextErr := service.client.context(ctx, append(options.RequestOptions, WithIdempotencyKey(chunkKey))...)
		if contextErr != nil {
			return nil, contextErr
		}
		command := &internalartifactv1.UploadArtifactChunkRequest{Name: upload.GetName(), ChunkIndex: upload.GetNextChunkIndex(), Offset: offset, Data: data, ChunkDigest: "sha256:" + hex.EncodeToString(chunkDigest[:]), Etag: upload.GetEtag()}
		commandDigest, digestErr := deterministicDigest(command)
		if digestErr != nil {
			chunkCancel()
			return nil, digestErr
		}
		command.Context = commandContext(service.client.config, chunkContext, chunkRequest, commandDigest)
		response, callErr := service.transport.UploadArtifactChunk(chunkContext, command)
		chunkCancel()
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		upload = response.GetUpload()
		if upload == nil || upload.GetCommittedOffset() != offset+int64(count) || upload.GetNextChunkIndex() != command.GetChunkIndex()+1 {
			return nil, &Error{Code: CodeDataLoss, Message: "artifact upload progress did not advance contiguously"}
		}
		offset = upload.GetCommittedOffset()
	}
	var extra [1]byte
	count, readErr := io.ReadFull(source, extra[:])
	if count != 0 {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload source exceeds declared size"}
	}
	if readErr != nil && !errors.Is(readErr, io.EOF) {
		return nil, normalizeError(readErr)
	}
	if "sha256:"+hex.EncodeToString(fullDigest.Sum(nil)) != artifact.GetDigest() {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload source digest differs from ArtifactRef"}
	}
	finalizeContext, finalizeRequest, finalizeCancel, err := service.client.context(ctx, append(options.RequestOptions, WithIdempotencyKey("artifact-upload:"+uploadID+":finalize"))...)
	if err != nil {
		return nil, err
	}
	receiptBase := time.Now().UTC()
	if upload.GetCreateTime() != nil && upload.GetCreateTime().IsValid() {
		receiptBase = upload.GetCreateTime().AsTime().UTC()
	}
	finalize := &internalartifactv1.FinalizeArtifactUploadRequest{Name: upload.GetName(), Etag: upload.GetEtag(), ReceiptExpireTime: timestamppb.New(receiptBase.Add(receiptTTL))}
	finalizeDigest, err := deterministicDigest(finalize)
	if err != nil {
		finalizeCancel()
		return nil, err
	}
	finalize.Context = commandContext(service.client.config, finalizeContext, finalizeRequest, finalizeDigest)
	finalized, err := service.transport.FinalizeArtifactUpload(finalizeContext, finalize)
	finalizeCancel()
	if err != nil {
		return nil, normalizeError(err)
	}
	receipt := finalized.GetStagingReceipt()
	if receipt == nil || receipt.GetArtifact() == nil || !proto.Equal(receipt.GetArtifact(), artifact) || !isSHA256Digest(receipt.GetReceiptDigest()) {
		return nil, &Error{Code: CodeDataLoss, Message: "artifact finalize returned an invalid staging receipt"}
	}
	return receipt, nil
}

// GetUpload returns clone-safe durable progress for a resumable upload.
func (service *ArtifactService) GetUpload(ctx context.Context, name string, options ...RequestOption) (*internalartifactv1.ArtifactUploadSession, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload name is required"}
	}
	return service.getUpload(ctx, name, options...)
}

func (service *ArtifactService) getUpload(ctx context.Context, name string, options ...RequestOption) (*internalartifactv1.ArtifactUploadSession, error) {
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetArtifactUpload(callContext, &internalartifactv1.GetArtifactUploadRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetUpload() == nil {
		return nil, &Error{Code: CodeDataLoss, Message: "artifact upload status returned no session"}
	}
	return proto.Clone(response.GetUpload()).(*internalartifactv1.ArtifactUploadSession), nil
}

// AbortUpload permanently aborts an incomplete session under ETag and
// idempotency protection.
func (service *ArtifactService) AbortUpload(ctx context.Context, name, etag, reasonCode string, options ...RequestOption) (*internalartifactv1.ArtifactUploadSession, error) {
	return service.transitionUpload(ctx, name, etag, reasonCode, false, options...)
}

// QuarantineUpload permanently quarantines a corrupt or policy-rejected
// session under ETag and idempotency protection.
func (service *ArtifactService) QuarantineUpload(ctx context.Context, name, etag, reasonCode string, options ...RequestOption) (*internalartifactv1.ArtifactUploadSession, error) {
	return service.transitionUpload(ctx, name, etag, reasonCode, true, options...)
}

func (service *ArtifactService) transitionUpload(ctx context.Context, name, etag, reasonCode string, quarantine bool, options ...RequestOption) (*internalartifactv1.ArtifactUploadSession, error) {
	name, etag, reasonCode = strings.TrimSpace(name), strings.TrimSpace(etag), strings.TrimSpace(reasonCode)
	if name == "" || etag == "" || reasonCode == "" {
		return nil, &Error{Code: CodeInvalidArgument, Message: "artifact upload name, ETag, and reason are required"}
	}
	transition := "abort"
	expected := internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_ABORTED
	if quarantine {
		transition = "quarantine"
		expected = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_QUARANTINED
	}
	identity := sha256.Sum256([]byte(name + "\x00" + transition + "\x00" + reasonCode))
	callContext, requestMetadata, cancel, err := service.client.context(ctx, append(options, WithIdempotencyKey("artifact-transfer:"+hex.EncodeToString(identity[:])))...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	var upload *internalartifactv1.ArtifactUploadSession
	if quarantine {
		request := &internalartifactv1.QuarantineArtifactUploadRequest{Name: name, Etag: etag, ReasonCode: reasonCode}
		digest, digestErr := deterministicDigest(request)
		if digestErr != nil {
			return nil, digestErr
		}
		request.Context = commandContext(service.client.config, callContext, requestMetadata, digest)
		response, callErr := service.transport.QuarantineArtifactUpload(callContext, request)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		upload = response.GetUpload()
	} else {
		request := &internalartifactv1.AbortArtifactUploadRequest{Name: name, Etag: etag, ReasonCode: reasonCode}
		digest, digestErr := deterministicDigest(request)
		if digestErr != nil {
			return nil, digestErr
		}
		request.Context = commandContext(service.client.config, callContext, requestMetadata, digest)
		response, callErr := service.transport.AbortArtifactUpload(callContext, request)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		upload = response.GetUpload()
	}
	if upload == nil || upload.GetState() != expected {
		return nil, &Error{Code: CodeDataLoss, Message: "artifact upload transition returned an invalid terminal session"}
	}
	return proto.Clone(upload).(*internalartifactv1.ArtifactUploadSession), nil
}

func hasErrorCode(err error, code Code) bool {
	var sdkError *Error
	return errors.As(err, &sdkError) && sdkError.Code == code
}

func (service *ArtifactService) Commit(ctx context.Context, receipt *internalartifactv1.ArtifactStagingReceipt, options ...RequestOption) (*artifactv1.ArtifactRef, error) {
	if receipt == nil || receipt.GetArtifact() == nil || !isSHA256Digest(receipt.GetReceiptDigest()) {
		return nil, &Error{Code: CodeInvalidArgument, Message: "valid artifact staging receipt is required"}
	}
	callContext, request, cancel, err := service.client.context(ctx, append(options, WithIdempotencyKey("artifact-commit:"+receipt.GetReceiptDigest()))...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	command := &artifactv1.CommitArtifactCommand{Artifact: proto.Clone(receipt.GetArtifact()).(*artifactv1.ArtifactRef), StagingReceiptDigest: receipt.GetReceiptDigest()}
	digest, err := deterministicDigest(command)
	if err != nil {
		return nil, err
	}
	command.Context = commandContext(service.client.config, callContext, request, digest)
	response, err := service.transport.CommitArtifact(callContext, &internalartifactv1.CommitArtifactRequest{Command: command})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetArtifact() == nil || !proto.Equal(response.GetArtifact(), receipt.GetArtifact()) {
		return nil, &Error{Code: CodeDataLoss, Message: "artifact commit returned a different content identity"}
	}
	return response.GetArtifact(), nil
}

func validateUploadArtifact(artifact *artifactv1.ArtifactRef) error {
	if artifact == nil || !isSHA256Digest(artifact.GetDigest()) || artifact.GetIntegrityDigest() != "" && artifact.GetIntegrityDigest() != artifact.GetDigest() || strings.TrimSpace(artifact.GetMediaType()) == "" || artifact.GetSizeBytes() < 0 || (artifact.GetSchemaId() == "") != (artifact.GetSchemaVersion() == "") || artifact.GetUri() != "" {
		return &Error{Code: CodeInvalidArgument, Message: "a complete immutable ArtifactRef without a provider URI is required"}
	}
	return nil
}

func validUploadID(value string) bool {
	if value == "" || len(value) > 128 || value[0] == '.' || value[0] == '-' || value[0] == '_' {
		return false
	}
	for _, character := range value {
		if !(character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || character == '.' || character == '_' || character == '-') {
			return false
		}
	}
	return true
}

func isSHA256Digest(value string) bool {
	if len(value) != len("sha256:")+sha256.Size*2 || !strings.HasPrefix(value, "sha256:") {
		return false
	}
	decoded, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil && len(decoded) == sha256.Size
}
