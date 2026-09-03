package persistence

import "errors"

var ErrUnsafeMigration = errors.New("unsafe migration")

type Migration struct {
	Version string
	Expand  bool
	HasDown bool
}

func ValidateMigration(m Migration) error {
	if m.Version == "" || !m.Expand || !m.HasDown {
		return ErrUnsafeMigration
	}
	return nil
}
