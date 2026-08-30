package observability
import"fmt"
type Metric struct{Name string;Attributes map[string]string;Value float64};func(m Metric)Validate()error{if m.Name==""||len(m.Attributes)>16{return fmt.Errorf("invalid metric")};return nil}
