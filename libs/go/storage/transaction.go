package storage

import "context"

type (
	Transaction interface {
		Commit(context.Context) error
		Rollback(context.Context) error
	}
	Transactor interface {
		Within(context.Context, func(context.Context, Transaction) error) error
	}
)
