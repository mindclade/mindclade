package outbox

func CanAcknowledge(record DeliveryRecord, epoch uint64) bool {
	return record.DeliveryEpoch == epoch && record.DeliveredAt == nil
}
