package jobs

import (
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

const CreateAction = "jobs.create"

type CreateCommand struct {
	Principal policies.Principal
	Job       *jobv1.Job
}

func Create(authorizer policies.Authorizer, repository *Repository, command CreateCommand) error {
	if command.Job == nil {
		return ErrNotFound
	}
	if err := authorizer.Authorize(command.Principal, CreateAction, command.Job.GetTenantId()); err != nil {
		return err
	}
	return repository.CreateJob(command.Job)
}
