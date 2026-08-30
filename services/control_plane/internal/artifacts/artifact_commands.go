package artifacts

import (
	"context"
	"io"

	"github.com/mindclade/mindclade/services/control_plane/internal/platform/storage"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

const RegisterAction = "artifacts.register"

type RegisterCommand struct {
	Principal policies.Principal
	Artifact  Artifact
}

func Register(authorizer policies.Authorizer, repository *Repository, command RegisterCommand) error {
	if err := authorizer.Authorize(command.Principal, RegisterAction, command.Artifact.TenantID); err != nil {
		return err
	}
	return repository.Put(command.Artifact)
}

type FinalizeCommand struct {
	Principal policies.Principal
	Artifact  Artifact
	Body      io.Reader
}

// Finalize fences reserve/stage/verify/finalize/catalog work. Object writes occur before catalog commit.
func Finalize(ctx context.Context, authorizer policies.Authorizer, repository *Repository, cas storage.FilesystemCAS, catalog storage.Catalog, command FinalizeCommand) (Artifact, error) {
	if err := authorizer.Authorize(command.Principal, RegisterAction, command.Artifact.TenantID); err != nil {
		return Artifact{}, err
	}
	reserved, err := repository.Reserve(command.Artifact)
	if err != nil {
		return Artifact{}, err
	}
	reservation, err := cas.Reserve(reserved.TenantID, reserved.Digest, reserved.Size, reserved.Fence)
	if err != nil {
		return Artifact{}, err
	}
	staged, err := cas.Stage(ctx, reservation, command.Body)
	if err != nil {
		return Artifact{}, err
	}
	if err = cas.Verify(staged, reservation); err != nil {
		return Artifact{}, err
	}
	if _, err = cas.Finalize(staged, reservation); err != nil {
		return Artifact{}, err
	}
	if err = catalog.Register(ctx, storage.ArtifactRecord{TenantID: reserved.TenantID, Digest: reserved.Digest, MediaType: reserved.MediaType, Size: reserved.Size}); err != nil {
		return Artifact{}, err
	}
	if err = repository.Put(reserved); err != nil {
		return Artifact{}, err
	}
	return reserved, nil
}
