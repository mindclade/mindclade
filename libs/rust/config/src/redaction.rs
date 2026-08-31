use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

pub fn redact(values: &BTreeMap<String, Value>, sensitive: &[String]) -> BTreeMap<String, Value> {
    let sensitive: BTreeSet<&str> = sensitive.iter().map(String::as_str).collect();
    values
        .iter()
        .map(|(key, value)| {
            (
                key.clone(),
                if sensitive.contains(key.as_str()) {
                    json!({"redacted": true})
                } else {
                    value.clone()
                },
            )
        })
        .collect()
}
