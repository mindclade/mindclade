# Wave 1 local integration

The local profile starts one digest-pinned PostgreSQL instance on loopback. The
queue emulator, fake identity issuer, and filesystem content-addressed store run
inside test processes and receive attempt-scoped temporary directories.

The profile contains no reusable credentials. PostgreSQL trust authentication
is acceptable only because the published port binds to `127.0.0.1`, the data
directory is ephemeral, and the profile is prohibited outside local tests.

Use `just integration-up`, `just integration-test`, and `just integration-down`.
The cleanup recipe removes the ephemeral PostgreSQL volume and orphaned local
containers. Never adapt this file into a production deployment.
