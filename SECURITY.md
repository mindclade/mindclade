# Security Policy

## Reporting a vulnerability

Do not open a public issue. Use the private GitHub security-advisory workflow
for `mindclade/mindclade` and include the affected revision, impact, minimal
reproduction, and whether credentials, tenants, biological data, or release
integrity may be involved. Do not attach secrets or protected payloads.

## Supported state

The repository is pre-production and Wave 0. No product version is currently
supported. Security controls are source-qualified only when their exact checks
pass; connected GitHub, signer, cloud, and recovery controls require separate
evidence.

## Mandatory handling

- Treat credentials, private keys, signing material, kubeconfigs, provider
  state, customer data, protected biological data, model weights, checkpoints,
  and generated datasets as prohibited Git content.
- Revoke exposed credentials and quarantine affected artifacts before history
  repair. Preserve forensic evidence through the approved incident channel.
- Pin third-party actions and build inputs immutably. Release promotion accepts
  verified digests, never mutable tags.
- Report suspected biological-safety or scientific-integrity failures through
  the private security-control-gap process and involve the accountable domain
  owner.

Security fixes follow the same protected review and evidence gates as other
changes. Emergency connected mutation requires audited break-glass authority
and a mandatory reconciliation pull request.
