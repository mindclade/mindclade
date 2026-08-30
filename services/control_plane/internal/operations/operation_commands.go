package operations

import (
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

const CreateAction = "operations.create"

type CreateCommand struct {
	Principal      policies.Principal
	Operation      Operation
	IdempotencyKey string
}

func Create(authorizer policies.Authorizer, repository *Repository, command CreateCommand) (Operation, bool, error) {
	if err := authorizer.Authorize(command.Principal, CreateAction, command.Operation.TenantID); err != nil {
		return Operation{}, false, err
	}
	return repository.CreateAtomically(command.Operation, command.IdempotencyKey, command.Principal.ID)
}
