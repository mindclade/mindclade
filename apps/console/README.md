# Internal console control-plane integration

This package is a private, unpublished server-side data source for the Mindclade console. It consumes only `@mindclade/internal-sdk`: generated transports stay behind that SDK, and PostgreSQL, Pub/Sub, and GCS remain inaccessible service-side capabilities.

The current bounded surface lists, reads, cancels, and watches durable operations and resolves/downloads content-addressed artifacts. The SDK owns workload identity, TLS, tenant expectations, deadlines, idempotency, error normalization, stream resumption, and digest validation. Browser bundles must call a server route backed by this module rather than receive workload credentials.
