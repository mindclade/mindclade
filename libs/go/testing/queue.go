package testing

type Queue[T any] struct{ items []T }

func (q *Queue[T]) Push(v T) { q.items = append(q.items, v) }
func (q *Queue[T]) Pop() (T, bool) {
	var z T
	if len(q.items) == 0 {
		return z, false
	}
	v := q.items[0]
	q.items = q.items[1:]
	return v, true
}
