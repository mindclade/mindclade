package observability
import"context"
type traceKey struct{};type TraceID string;func WithTrace(c context.Context,id TraceID)context.Context{return context.WithValue(c,traceKey{},id)};func TraceFrom(c context.Context)(TraceID,bool){v,ok:=c.Value(traceKey{}).(TraceID);return v,ok&&v!=""}
