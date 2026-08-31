package testing

import "errors"

type Failure struct{ Remaining int }

func (f *Failure) Next() error {
	if f.Remaining == 0 {
		return nil
	}
	f.Remaining--
	return errors.New("injected failure")
}
