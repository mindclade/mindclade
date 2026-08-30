package outbox

func CanAcknowledge(message Message, epoch uint64) bool {
	return message.DeliveryEpoch == epoch && message.DeliveredAt == nil
}
