# Validate Metadata Action

This composite action provides a small credential-free guard for callers that
already checked out the exact revision. The organization reusable metadata
workflow remains the CI implementation authority and performs the complete
trusted-context and evidence flow.

The local action intentionally validates only canonical root identity and
required files. It cannot change repository settings or replace the component,
owner, path-manifest, or drift validators.
