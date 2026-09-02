import {
	ClientConfig,
	type Environment,
	GcpWorkloadIdentityProvider,
	type Identity,
	MindcladeClient,
	type TokenProvider,
} from "@mindclade/internal-sdk";

export interface ControlPlaneClientOptions {
	readonly environment: Environment;
	readonly identity: Identity;
	readonly endpoint?: string;
	readonly audience?: string;
	readonly defaultTimeoutMs?: number;
	readonly tokenProvider?: TokenProvider;
	readonly tls?: {
		readonly caPem?: string;
		readonly serverName?: string;
	};
	readonly insecureLoopbackForTesting?: boolean;
}

/** Builds immutable SDK policy for the console's server-side data boundary. */
export const createControlPlaneConfig = (options: ControlPlaneClientOptions): ClientConfig => {
	const localPlaintext = options.insecureLoopbackForTesting === true;
	const tokenProvider = localPlaintext
		? undefined
		: (options.tokenProvider ?? new GcpWorkloadIdentityProvider());
	return ClientConfig.create({
		environment: options.environment,
		identity: options.identity,
		...(options.endpoint === undefined ? {} : { endpoint: options.endpoint }),
		...(options.audience === undefined ? {} : { audience: options.audience }),
		...(options.defaultTimeoutMs === undefined
			? {}
			: { defaultTimeoutMs: options.defaultTimeoutMs }),
		...(tokenProvider === undefined ? {} : { tokenProvider }),
		...(options.tls === undefined ? {} : { tls: options.tls }),
		...(localPlaintext ? { insecureLoopbackForTesting: true } : {}),
	});
};

/** Creates the native-gRPC internal client. Keep this module on the server. */
export const createControlPlaneClient = (options: ControlPlaneClientOptions): MindcladeClient =>
	MindcladeClient.connect(createControlPlaneConfig(options));
