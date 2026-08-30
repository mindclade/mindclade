package storage
import("context";"time")
type OutboxMessage struct{ID,Topic,PayloadDigest string;DeliveryEpoch uint64;AvailableAt time.Time};type Outbox interface{Enqueue(context.Context,OutboxMessage)error;Claim(context.Context,int,time.Time)([]OutboxMessage,error);Acknowledge(context.Context,string,uint64)error}
