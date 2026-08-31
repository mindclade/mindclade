package faults

func Retryable(e error) bool { return Classify(e) == Conflict || Classify(e) == Unavailable }
