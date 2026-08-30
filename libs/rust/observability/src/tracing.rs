#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TraceContext { pub trace_id: String, pub span_id: String }
impl TraceContext { pub fn new(trace_id: &str, span_id: &str) -> Result<Self, &'static str> { if trace_id.len() != 32 || span_id.len() != 16 || !trace_id.chars().chain(span_id.chars()).all(|value| value.is_ascii_hexdigit() && !value.is_ascii_uppercase()) { return Err("trace identifiers must be lowercase hexadecimal"); } Ok(Self { trace_id: trace_id.into(), span_id: span_id.into() }) } }
