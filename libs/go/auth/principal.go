package auth

import "errors"

type Principal struct {
	Subject, TenantID string
	Authenticated     bool
}

func NewPrincipal(s, t string) (Principal, error) {
	if s == "" || t == "" {
		return Principal{}, errors.New("principal identity required")
	}
	return Principal{s, t, true}, nil
}
