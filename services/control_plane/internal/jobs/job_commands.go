package jobs

import "github.com/mindclade/mindclade/services/control_plane/internal/policies"

const CreateAction = "jobs.create"

type CreateCommand struct {
	Principal policies.Principal
	Job       Job
}

func Create(authorizer policies.Authorizer, repository *Repository, command CreateCommand) error {
	if err := authorizer.Authorize(command.Principal, CreateAction, command.Job.TenantID); err != nil {
		return err
	}
	return repository.CreateJob(command.Job)
}
