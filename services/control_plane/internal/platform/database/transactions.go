package database

import "context"

// Transaction is intentionally opaque: repositories expose no transaction object to workers.
type Transaction interface {
	AfterCommit(func(context.Context) error)
}

type Runner interface {
	WithinTransaction(context.Context, func(Transaction) error) error
}

// NoExternalEffects documents the kernel rule: callbacks schedule delivery after commit only.
type NoExternalEffects struct{}

func (NoExternalEffects) AfterCommit(func(context.Context) error) {}
