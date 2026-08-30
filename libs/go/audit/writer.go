package audit
import("context";"sync")
type Writer interface{Append(context.Context,Event)error};type MemoryWriter struct{mu sync.Mutex;events []Event}
func(w *MemoryWriter)Append(c context.Context,e Event)error{if err:=c.Err();err!=nil{return err};w.mu.Lock();defer w.mu.Unlock();w.events=append(w.events,e);return nil};func(w *MemoryWriter)Events()[]Event{w.mu.Lock();defer w.mu.Unlock();return append([]Event(nil),w.events...)}
