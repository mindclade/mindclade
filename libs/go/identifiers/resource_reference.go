package identifiers
import"fmt"
type ResourceRef struct{TenantID,ProjectID,ResourceType string;ResourceID ResourceID;Version uint64};func(r ResourceRef)Validate()error{if r.TenantID==""||r.ProjectID==""||r.ResourceType==""||r.ResourceID.Kind!=r.ResourceType||r.Version==0{return fmt.Errorf("invalid resource reference")};return nil}
