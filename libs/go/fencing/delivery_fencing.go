// Package fencing decides whether a fenced actor may still act on shared state.
//
// A fence is the epoch a claim was granted under. An actor holding a stale
// epoch has been superseded and must not complete its work, so every predicate
// here is written over the epoch and the terminal marker alone: taking the
// caller's record type would invert the dependency and make the primitive
// unusable from the packages that need it most.
package fencing

import "time"

// CanAcknowledge reports whether a delivery claimed under claimedEpoch may
// still acknowledge against the fence held at currentEpoch. A delivery that
// already recorded a delivery time is terminal and never acknowledges twice.
func CanAcknowledge(claimedEpoch, currentEpoch uint64, deliveredAt *time.Time) bool {
	return claimedEpoch == currentEpoch && deliveredAt == nil
}
