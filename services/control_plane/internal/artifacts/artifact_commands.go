package artifacts

import (
	"context"
	"io"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/storage"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

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
