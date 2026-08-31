package clock

import (
	"context"
	"testing"
	"time"
)

func TestClock(t *testing.T) {
	n := time.Now().UTC()
	c := NewManual(n)
	if err := c.Sleep(context.Background(), time.Second); err != nil {
		t.Fatal(err)
	}
	if c.Now().Equal(n) {
		t.Fatal("not advanced")
	}
}
