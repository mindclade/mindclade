# Source Mirror Inventory

`sources.lock.json` records the immutable source identity and build authority
for third-party source intake. Modern DeepEP 2.x is pinned with its `fmt`
submodule and resolved for SM90 through the repository's pinned nixpkgs input
by `nix develop .#gpu`. The package uses the NCCL Gin backend and vanilla
NVSHMEM 3.3.9 or later for the legacy objects still required by upstream. It
is not vendored, mirrored, activated, or approved for production use.

If a controlled mirror becomes necessary for release isolation, add its
immutable location and digest to the existing entry before the build consumes
it. Mutable branch names, floating tags, and configure-time downloads are not
valid source identities.
