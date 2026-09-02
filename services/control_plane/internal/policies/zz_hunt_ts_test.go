
// originMainClockNow reproduces the clock on origin/main verbatim:
//
//	git show origin/main:.../contracts.go
//	func (realClock) Now() time.Time { return time.Now().UTC() }
func originMainClockNow() time.Time { return time.Now().UTC() }
