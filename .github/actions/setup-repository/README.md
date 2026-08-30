# Set Up Repository Action

This bounded composite action validates an existing credential-free checkout at
one exact commit and confirms the Wave 0 native locks. It does not install a
toolchain, persist a Git credential, dispatch CI, assume cloud identity, build a
release, or mutate repository state.

Call it only after a digest-pinned checkout with `persist-credentials: false`.
The heavy build environment is the locked Nix shell used by Buildkite.
