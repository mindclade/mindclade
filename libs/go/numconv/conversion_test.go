package numconv

import (
	"errors"
	"math"
	"strconv"
	"testing"
)

func TestInt64ToUint64(t *testing.T) {
	t.Parallel()
	for _, test := range []struct {
		name    string
		input   int64
		want    uint64
		wantErr bool
	}{
		{name: "zero", input: 0, want: 0},
		{name: "maximum", input: math.MaxInt64, want: math.MaxInt64},
		{name: "negative", input: -1, wantErr: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			got, err := Int64ToUint64(test.input)
			if test.wantErr {
				assertRangeError(t, err, "int64", "uint64")
				return
			}
			if err != nil || got != test.want {
				t.Fatalf("got (%d, %v), want (%d, nil)", got, err, test.want)
			}
		})
	}
}

func TestInt64ToUint32(t *testing.T) {
	t.Parallel()
	for _, test := range []struct {
		name    string
		input   int64
		want    uint32
		wantErr bool
	}{
		{name: "zero", input: 0, want: 0},
		{name: "maximum", input: math.MaxUint32, want: math.MaxUint32},
		{name: "negative", input: -1, wantErr: true},
		{name: "overflow", input: int64(math.MaxUint32) + 1, wantErr: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			got, err := Int64ToUint32(test.input)
			if test.wantErr {
				assertRangeError(t, err, "int64", "uint32")
				return
			}
			if err != nil || got != test.want {
				t.Fatalf("got (%d, %v), want (%d, nil)", got, err, test.want)
			}
		})
	}
}

func TestIntToUint32(t *testing.T) {
	t.Parallel()
	for _, test := range []struct {
		name    string
		input   int
		want    uint32
		wantErr bool
	}{
		{name: "zero", input: 0, want: 0},
		{name: "bounded", input: 200, want: 200},
		{name: "negative", input: -1, wantErr: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			got, err := IntToUint32(test.input)
			if test.wantErr {
				assertRangeError(t, err, "int", "uint32")
				return
			}
			if err != nil || got != test.want {
				t.Fatalf("got (%d, %v), want (%d, nil)", got, err, test.want)
			}
		})
	}
}

func TestUint32ToInt(t *testing.T) {
	t.Parallel()
	for _, value := range []uint32{0, 200, math.MaxUint32} {
		got, err := Uint32ToInt(value)
		if uint64(value) > uint64(^uint(0)>>1) {
			assertRangeError(t, err, "uint32", "int")
			continue
		}
		if err != nil || strconv.Itoa(got) != strconv.FormatUint(uint64(value), 10) {
			t.Fatalf("got (%d, %v), want (%d, nil)", got, err, value)
		}
	}
}

func TestUint32ToInt32(t *testing.T) {
	t.Parallel()
	for _, test := range []struct {
		name    string
		input   uint32
		want    int32
		wantErr bool
	}{
		{name: "zero", input: 0, want: 0},
		{name: "maximum", input: math.MaxInt32, want: math.MaxInt32},
		{name: "overflow", input: uint32(math.MaxInt32) + 1, wantErr: true},
		{name: "uint32 maximum", input: math.MaxUint32, wantErr: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			got, err := Uint32ToInt32(test.input)
			if test.wantErr {
				assertRangeError(t, err, "uint32", "int32")
				return
			}
			if err != nil || got != test.want {
				t.Fatalf("got (%d, %v), want (%d, nil)", got, err, test.want)
			}
		})
	}
}

func TestUint64ToInt64(t *testing.T) {
	t.Parallel()
	for _, test := range []struct {
		name    string
		input   uint64
		want    int64
		wantErr bool
	}{
		{name: "zero", input: 0, want: 0},
		{name: "maximum", input: math.MaxInt64, want: math.MaxInt64},
		{name: "overflow", input: uint64(math.MaxInt64) + 1, wantErr: true},
		{name: "uint64 maximum", input: math.MaxUint64, wantErr: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			got, err := Uint64ToInt64(test.input)
			if test.wantErr {
				assertRangeError(t, err, "uint64", "int64")
				return
			}
			if err != nil || got != test.want {
				t.Fatalf("got (%d, %v), want (%d, nil)", got, err, test.want)
			}
		})
	}
}

func assertRangeError(t *testing.T, err error, source, target string) {
	t.Helper()
	if !errors.Is(err, ErrOutOfRange) {
		t.Fatalf("expected ErrOutOfRange, got %v", err)
	}
	var rangeErr *RangeError
	if !errors.As(err, &rangeErr) {
		t.Fatalf("expected RangeError, got %T", err)
	}
	if rangeErr.Source != source || rangeErr.Target != target {
		t.Fatalf("unexpected range metadata: %#v", rangeErr)
	}
}
