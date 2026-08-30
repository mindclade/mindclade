package storage
import("context";"time")
type Lease struct{ResourceID,Holder string;Epoch uint64;ExpiresAt time.Time};type LeaseStore interface{Acquire(context.Context,string,string,time.Time)(Lease,error);Current(context.Context,string)(Lease,error)}
