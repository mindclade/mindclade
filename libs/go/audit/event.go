package audit
import ("fmt";"time")
type Event struct{TenantID,PrincipalID,Action,Resource,Outcome string;OccurredAt time.Time;Fields map[string]string}
func NewEvent(t,p,a,r,o string,at time.Time,f map[string]string)(Event,error){if t==""||p==""||a==""||r==""||at.Location()!=time.UTC||(o!="allowed"&&o!="denied"){return Event{},fmt.Errorf("invalid audit event")};c:=map[string]string{};for k,v:=range f{if k==""||len(v)>1024{return Event{},fmt.Errorf("invalid audit field")};c[k]=v};return Event{t,p,a,r,o,at,c},nil}
