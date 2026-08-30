package auth
import"context"
type Decision uint8
const(Deny Decision=iota;Allow)
type Request struct{Principal Principal;Action,Resource string};type Authorizer interface{Authorize(context.Context,Request)Decision};type RuleAuthorizer struct{Allowed map[string]map[string]struct{}}
func(a RuleAuthorizer)Authorize(c context.Context,r Request)Decision{if c.Err()!=nil||r.Principal.Authenticated==false||r.Action==""||r.Resource==""{return Deny};x,ok:=a.Allowed[r.Principal.Subject+":"+r.Action];if ok==false{return Deny};if _,ok=x[r.Resource];ok{return Allow};if _,ok=x["*"];ok{return Allow};return Deny}
