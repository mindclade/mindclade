package clock
import("context";"time")
type Clock interface{Now()time.Time;Sleep(context.Context,time.Duration)error};type System struct{}
func(System)Now()time.Time{return time.Now().UTC()};func(System)Sleep(c context.Context,d time.Duration)error{timer:=time.NewTimer(d);defer timer.Stop();select{case<-c.Done():return c.Err();case<-timer.C:return nil}}
