use crate::redaction::redact;
use serde_json::Value;
use sha2::{Digest as _, Sha256};
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq)]
pub struct ConfigLayer {
    pub precedence: u8,
    pub name: String,
    pub values: BTreeMap<String, Value>,
}
#[derive(Clone, Debug, PartialEq)]
pub struct Resolution {
    pub values: BTreeMap<String, Value>,
    pub provenance: BTreeMap<String, String>,
    pub digest: String,
}

/// Resolves configuration layers in precedence order and records provenance.
///
/// # Errors
///
/// Returns an error when layer precedence values are not unique or when the
/// redacted configuration cannot be serialized for digesting.
pub fn resolve(
    mut layers: Vec<ConfigLayer>,
    sensitive: &[String],
) -> Result<Resolution, &'static str> {
    layers.sort_by_key(|layer| layer.precedence);
    if layers
        .windows(2)
        .any(|pair| pair[0].precedence == pair[1].precedence)
    {
        return Err("configuration precedence must be unique");
    }
    let mut values = BTreeMap::new();
    let mut provenance = BTreeMap::new();
    for layer in layers {
        for (key, value) in layer.values {
            values.insert(key.clone(), value);
            provenance.insert(key, layer.name.clone());
        }
    }
    let canonical = serde_json::to_vec(&redact(&values, sensitive))
        .map_err(|_| "configuration is not serializable")?;
    Ok(Resolution {
        values,
        provenance,
        digest: format!("sha256:{:x}", Sha256::digest(canonical)),
    })
}
