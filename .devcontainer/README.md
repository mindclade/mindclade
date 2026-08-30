# Development Container

The container is a thin, digest-pinned host for the locked Nix environment. It
does not contain production credentials or an independent toolchain definition.

Open the repository in a devcontainer-capable editor. Creation mounts a named
Nix-store cache, evaluates `flake.lock`, and runs `just bootstrap`. Run
`just doctor` after creation. The container must remain useful without cloud,
GitHub, Kubernetes, or artifact-registry credentials.

The base image is pinned by OCI index digest. Updating it requires multi-platform
inspection, rebuild, bootstrap and doctor evidence, and a reviewed digest change.
