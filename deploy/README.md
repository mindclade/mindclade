# Deployment source boundary

This directory contains local composition inputs and future immutable release
consumers. It does not own live environment state, cloud resources, GitOps
desired state, credentials, or product build authority.

Wave 1 activates only the loopback local integration profile. It cannot publish,
promote, or deploy a release.
