package audit

import (
	"sync"
	"time"
)

type Event struct {
	ID        string
	TenantID  string
	ActorID   string
	Action    string
	SubjectID string
	At        time.Time
}

type Store struct {
	mu     sync.Mutex
	events []Event
}

func (s *Store) Append(event Event) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.events = append(s.events, event)
}

func (s *Store) Events(tenantID string) []Event {
	s.mu.Lock()
	defer s.mu.Unlock()
	result := make([]Event, 0, len(s.events))
	for _, event := range s.events {
		if event.TenantID == tenantID {
			result = append(result, event)
		}
	}
	return result
}
