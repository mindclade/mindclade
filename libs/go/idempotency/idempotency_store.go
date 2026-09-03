package idempotency

import (
	"errors"
	"sync"
)

var ErrHashConflict = errors.New("idempotency key reused with a different request hash")

type Record struct {
	RequestHash string
	ResultID    string
}

type Store struct {
	mu      sync.Mutex
	records map[CommandKey]Record
}

func NewStore() *Store { return &Store{records: make(map[CommandKey]Record)} }

// GetOrPut returns an existing result only when the canonical request hash is identical.
func (s *Store) GetOrPut(key CommandKey, hash, resultID string) (Record, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if existing, ok := s.records[key]; ok {
		if existing.RequestHash != hash {
			return Record{}, false, ErrHashConflict
		}
		return existing, true, nil
	}
	record := Record{RequestHash: hash, ResultID: resultID}
	s.records[key] = record
	return record, false, nil
}
