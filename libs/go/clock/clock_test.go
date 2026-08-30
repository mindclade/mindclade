package clock
import("context";"testing";"time")
func TestClock(t *testing.T){n:=time.Now().UTC();c:=NewManual(n);c.Sleep(context.Background(),time.Second);if c.Now().Equal(n){t.Fatal("not advanced")}}
