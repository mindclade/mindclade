package testing

import "context"

type RecordingTransaction struct{ Committed bool }

func (t *RecordingTransaction) Commit(c context.Context) error   { t.Committed = true; return c.Err() }
func (t *RecordingTransaction) Rollback(c context.Context) error { return c.Err() }
