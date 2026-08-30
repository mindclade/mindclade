package auth
import("fmt";"time")
type Delegation struct{TenantID,Subject,Action,ResourcePrefix string;LeaseEpoch uint64;ExpiresAt time.Time}
func(d Delegation)ValidAt(now time.Time)error{if d.TenantID==""||d.Subject==""||d.Action==""||d.ResourcePrefix==""||d.LeaseEpoch==0||now.Before(d.ExpiresAt)==false{return fmt.Errorf("invalid delegation")};return nil}
