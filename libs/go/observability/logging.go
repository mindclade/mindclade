package observability
import"time"
type LogRecord struct{Level,Message string;At time.Time;Fields map[string]string}
