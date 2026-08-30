package auth
import"fmt"
type Principal struct{Subject,TenantID string;Authenticated bool}
func NewPrincipal(s,t string)(Principal,error){if s==""||t==""{return Principal{},fmt.Errorf("principal identity required")};return Principal{s,t,true},nil}
