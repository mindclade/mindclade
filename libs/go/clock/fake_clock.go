package clock
import("context";"sync";"time")
type Manual struct{mu sync.Mutex;now time.Time};func NewManual(now time.Time)*Manual{return &Manual{now:now.UTC()}};func(c *Manual)Now()time.Time{c.mu.Lock();defer c.mu.Unlock();return c.now};func(c *Manual)Sleep(x context.Context,d time.Duration)error{if err:=x.Err();err!=nil{return err};c.Advance(d);return nil};func(c *Manual)Advance(d time.Duration){c.mu.Lock();defer c.mu.Unlock();c.now=c.now.Add(d)}
