import {
	type EnvironmentSource,
	MindcladeClient,
	type TokenProvider,
} from "@mindclade/internal-sdk";

/**
 * Build a client whose addressing comes from the `MINDCLADE_*` variables.
 *
 * `fromEnvironment` is the SDK's only environment-reading entry point: it owns
 * the variable names, their validation, and the endpoint and audience they
 * imply, so an application never re-implements that parsing and never drifts
 * from the other language SDKs. The workload identity provider stays an
 * explicit argument because no environment variable may ever carry a
 * credential. Passing `env` reads a supplied environment instead of the
 * process one, which is how a test configures a client without exporting
 * anything.
 */
export function clientFromEnvironment(
	tokenProvider: TokenProvider,
	env?: EnvironmentSource,
): MindcladeClient {
	return MindcladeClient.fromEnvironment({
		tokenProvider,
		...(env === undefined ? {} : { env }),
	});
}
