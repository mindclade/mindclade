// Package numconv provides checked conversions at signed database and
// unsigned protobuf boundaries.
package numconv

import (
	"errors"
	"fmt"
	"math"
	"strconv"
)

// ErrOutOfRange identifies a conversion whose input cannot be represented by
// the destination type.
var ErrOutOfRange = errors.New("numeric conversion out of range")

// RangeError describes a rejected conversion without discarding the original
// value. Callers can use errors.Is(err, ErrOutOfRange) or errors.As.
type RangeError struct {
	Source string
	Target string
	Value  string
}

func (e *RangeError) Error() string {
	return fmt.Sprintf("convert %s value %s to %s: %v", e.Source, e.Value, e.Target, ErrOutOfRange)
}

// Unwrap supports errors.Is with ErrOutOfRange.
func (e *RangeError) Unwrap() error { return ErrOutOfRange }

// Int64ToUint64 converts value only when it is representable as uint64.
func Int64ToUint64(value int64) (uint64, error) {
	if value < 0 {
		return 0, &RangeError{Source: "int64", Target: "uint64", Value: strconv.FormatInt(value, 10)}
	}
	return uint64(value), nil
}

// Int64ToUint32 converts value only when it is representable as uint32.
func Int64ToUint32(value int64) (uint32, error) {
	if value < 0 || value > int64(math.MaxUint32) {
		return 0, &RangeError{Source: "int64", Target: "uint32", Value: strconv.FormatInt(value, 10)}
	}
	return uint32(value), nil
}

// Int64ToInt32 converts value only when it is representable as int32.
func Int64ToInt32(value int64) (int32, error) {
	if value < int64(math.MinInt32) || value > int64(math.MaxInt32) {
		return 0, &RangeError{Source: "int64", Target: "int32", Value: strconv.FormatInt(value, 10)}
	}
	return int32(value), nil
}

// IntToUint32 converts value only when it is representable as uint32.
func IntToUint32(value int) (uint32, error) {
	if value < 0 || uint64(value) > math.MaxUint32 {
		return 0, &RangeError{Source: "int", Target: "uint32", Value: strconv.Itoa(value)}
	}
	return uint32(value), nil
}

// Uint32ToInt converts value only when it is representable as int on the
// target architecture.
func Uint32ToInt(value uint32) (int, error) {
	maximumInt := uint64(^uint(0) >> 1)
	if uint64(value) > maximumInt {
		return 0, &RangeError{Source: "uint32", Target: "int", Value: strconv.FormatUint(uint64(value), 10)}
	}
	return int(value), nil
}

// Uint32ToInt32 converts value only when it is representable as int32.
func Uint32ToInt32(value uint32) (int32, error) {
	if value > math.MaxInt32 {
		return 0, &RangeError{Source: "uint32", Target: "int32", Value: strconv.FormatUint(uint64(value), 10)}
	}
	return int32(value), nil
}

// Uint64ToInt64 converts value only when it is representable as int64.
func Uint64ToInt64(value uint64) (int64, error) {
	if value > math.MaxInt64 {
		return 0, &RangeError{Source: "uint64", Target: "int64", Value: strconv.FormatUint(value, 10)}
	}
	return int64(value), nil
}

// Uint64ToUint32 converts value only when it is representable as uint32.
func Uint64ToUint32(value uint64) (uint32, error) {
	if value > math.MaxUint32 {
		return 0, &RangeError{Source: "uint64", Target: "uint32", Value: strconv.FormatUint(value, 10)}
	}
	return uint32(value), nil
}
