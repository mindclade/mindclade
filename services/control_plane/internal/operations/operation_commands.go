package operations

import (
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

const CreateAction = "operations.create"

type CreateCommand struct {
	Principal           policies.Principal
	Operation           *operationv1.Operation
	IdempotencyKey      string
	RequestDigest       string
	ConfigurationDigest string
}

func Create(authorizer policies.Authorizer, repository *Repository, command CreateCommand) (*operationv1.Operation, bool, error) {
	if command.Operation == nil {
		return nil, false, ErrNotFound
	}
	if err := authorizer.Authorize(command.Principal, CreateAction, command.Operation.GetTenantId()); err != nil {
		return nil, false, err
	}
	return repository.CreateAtomically(command.Operation, command.RequestDigest, command.ConfigurationDigest, command.IdempotencyKey, command.Principal.ID)
}
