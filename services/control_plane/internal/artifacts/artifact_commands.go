package artifacts

import (
	"context"
	"errors"
	"io"
	"os"
	"strings"

	"github.com/mindclade/mindclade/libs/go/storage"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	schemav1 "github.com/mindclade/mindclade/protocols/generated/go/schema/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

const maxSchemaDocumentBytes int64 = 64 << 20

const RegisterAction = "artifacts.register"

type RegisterCommand struct {
	Principal policies.Principal
	TenantID  string
	Artifact  *artifactv1.ArtifactRef
}

func Register(authorizer policies.Authorizer, repository *Repository, command RegisterCommand) error {
	if err := authorizer.Authorize(command.Principal, RegisterAction, command.TenantID); err != nil {
		return err
	}
	return repository.Put(command.TenantID, command.Artifact, 0)
}

type FinalizeCommand struct {
	Principal policies.Principal
	TenantID  string
	Artifact  *artifactv1.ArtifactRef
	Body      io.Reader
}

// Finalize fences reserve/stage/verify/finalize/catalog work. Object writes occur before catalog commit.
func Finalize(ctx context.Context, authorizer policies.Authorizer, repository *Repository, cas storage.FilesystemCAS, catalog storage.Catalog, command FinalizeCommand) (*artifactv1.ArtifactRef, error) {
	if err := authorizer.Authorize(command.Principal, RegisterAction, command.TenantID); err != nil {
		return nil, err
	}
	reserved, fence, err := repository.Reserve(command.TenantID, command.Artifact)
	if err != nil {
		return nil, err
	}
	reservation, err := cas.Reserve(command.TenantID, reserved.GetDigest(), reserved.GetSizeBytes(), fence)
	if err != nil {
		return nil, err
	}
	staged, err := cas.Stage(ctx, reservation, command.Body)
	if err != nil {
		return nil, err
	}
	if err = cas.Verify(staged, reservation); err != nil {
		return nil, err
	}
	if err = validateGovernedDocument(staged.Path, reserved); err != nil {
		cas.Quarantine(staged)
		return nil, err
	}
	if _, err = cas.Finalize(staged, reservation); err != nil {
		return nil, err
	}
	if err = catalog.Register(ctx, storage.ArtifactRecord{TenantID: command.TenantID, Digest: reserved.GetDigest(), MediaType: reserved.GetMediaType(), Size: reserved.GetSizeBytes()}); err != nil {
		return nil, err
	}
	if err = repository.Put(command.TenantID, reserved, fence); err != nil {
		return nil, err
	}
	return reserved, nil
}

// validateGovernedDocument makes generated JSON Schema validators part of the
// artifact admission boundary. SchemaId is the governed family identifier
// (for example, "artifact_manifest"); SchemaVersion remains the document's
// explicit compatibility version. Untyped binary artifacts leave both empty.
func validateGovernedDocument(path string, ref *artifactv1.ArtifactRef) error {
	if ref.GetSchemaId() == "" {
		if ref.GetSchemaVersion() != "" {
			return errors.New("schema_version requires a governed schema_id")
		}
		return nil
	}
	if ref.GetSchemaVersion() == "" {
		return errors.New("governed JSON artifacts require schema_version")
	}
	if ref.GetMediaType() != "application/json" && !strings.HasSuffix(ref.GetMediaType(), "+json") {
		return errors.New("governed schema validation requires a JSON media type")
	}
	if ref.GetSizeBytes() > maxSchemaDocumentBytes {
		return errors.New("governed schema document exceeds the validation limit")
	}
	file, err := os.Open(path) // #nosec G304 -- path is an opaque staged CAS handle.
	if err != nil {
		return err
	}
	defer func() { _ = file.Close() }()
	content, err := io.ReadAll(io.LimitReader(file, maxSchemaDocumentBytes+1))
	if err != nil {
		return err
	}
	if int64(len(content)) > maxSchemaDocumentBytes {
		return errors.New("governed schema document exceeds the validation limit")
	}
	if err = schemav1.ValidateDocument(ref.GetSchemaId(), content); err != nil {
		return err
	}
	return nil
}
