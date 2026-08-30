package identifiers
import("fmt";"strings")
type ResourceID struct{Kind,Value string};func ParseResourceID(k,v string)(ResourceID,error){if k==""||len(v)<10||strings.HasPrefix(v,k+"_")==false{return ResourceID{},fmt.Errorf("invalid resource id")};return ResourceID{k,v},nil}
