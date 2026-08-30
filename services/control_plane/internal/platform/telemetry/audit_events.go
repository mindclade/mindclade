package telemetry

type AuditEvent struct {
	TenantID  string
	Action    string
	SubjectID string
}

type AuditSink interface {
	EmitAudit(AuditEvent)
}
