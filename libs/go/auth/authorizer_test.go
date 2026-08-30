package auth
import("context";"testing")
func TestAuthorizer(t *testing.T){p,_:=NewPrincipal("p","t");a:=RuleAuthorizer{};if a.Authorize(context.Background(),Request{p,"read","x"})!=Deny{t.Fatal("default allow")}}
