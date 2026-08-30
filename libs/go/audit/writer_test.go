package audit
import("context";"testing";"time")
func TestWriter(t *testing.T){e,err:=NewEvent("t","p","read","r","allowed",time.Now().UTC(),nil);if err!=nil{t.Fatal(err)};w:=new(MemoryWriter);if err=w.Append(context.Background(),e);err!=nil{t.Fatal(err)};if len(w.Events())!=1{t.Fatal("missing event")}}
