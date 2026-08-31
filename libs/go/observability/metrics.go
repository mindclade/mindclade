package observability

import "errors"

type Metric struct {
	Name       string
	Attributes map[string]string
	Value      float64
}

func (m Metric) Validate() error {
	if m.Name == "" || len(m.Attributes) > 16 {
		return errors.New("invalid metric")
	}
	return nil
}
