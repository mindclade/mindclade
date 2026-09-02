use std::{env, io, path::PathBuf, sync::Arc, time::Duration};

use mindclade_ingestion_worker::SourceFetcher;
use mindclade_internal_sdk::{
    Client, Config, Environment, GcpWorkloadIdentityProvider, Identity, TokenProvider,
};

const MAX_ENVELOPE_BYTES: u64 = 8 << 20;

/// The deadline the SDK enforces for every worker RPC, including its retries.
/// The worker owns no second timer of its own.
const RPC_TIMEOUT: Duration = Duration::from_secs(20);

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments = env::args_os().skip(1).collect::<Vec<_>>();
    if arguments.len() != 2 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "usage: mindclade-ingestion-worker-client EVENT.pb DESTINATION",
        )
        .into());
    }
    let envelope_path = PathBuf::from(&arguments[0]);
    let destination = PathBuf::from(&arguments[1]);
    if tokio::fs::metadata(&envelope_path).await?.len() > MAX_ENVELOPE_BYTES {
        return Err(
            io::Error::new(io::ErrorKind::InvalidData, "event envelope is too large").into(),
        );
    }
    let envelope = tokio::fs::read(envelope_path).await?;
    let (config, identity) = runtime_config()?;
    let client = Client::connect(config).await?;
    let assignment = SourceFetcher::new(client, identity, None)?
        .materialize(&envelope, &destination)
        .await?;
    println!(
        "event_id={} job_id={} configuration={}",
        assignment.event_id,
        assignment.job_id,
        assignment.configuration_path.display()
    );
    Ok(())
}

fn runtime_config() -> Result<(Config, Identity), Box<dyn std::error::Error>> {
    let environment = match env::var("MINDCLADE_ENVIRONMENT")
        .unwrap_or_else(|_| "development".to_owned())
        .as_str()
    {
        "local" => Environment::Local,
        "development" => Environment::Development,
        "staging" => Environment::Staging,
        "production" => Environment::Production,
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "MINDCLADE_ENVIRONMENT is invalid",
            )
            .into());
        }
    };
    let identity = Identity::new(
        required_env("MINDCLADE_TENANT_ID")?,
        required_env("MINDCLADE_PROJECT_ID")?,
        required_env("MINDCLADE_PRINCIPAL_ID")?,
    )?;
    let endpoint = env::var("MINDCLADE_ENDPOINT").ok();
    if environment == Environment::Local {
        let mut builder =
            Config::local_insecure_builder(identity.clone()).default_rpc_timeout(RPC_TIMEOUT);
        if let Some(endpoint) = endpoint {
            builder = builder.endpoint(endpoint);
        }
        return Ok((builder.build()?, identity));
    }
    let provider: Arc<dyn TokenProvider> =
        Arc::new(GcpWorkloadIdentityProvider::new(Duration::from_secs(10))?);
    let mut builder =
        Config::builder(environment, identity.clone(), provider).default_rpc_timeout(RPC_TIMEOUT);
    if let Some(endpoint) = endpoint {
        builder = builder.endpoint(endpoint);
    }
    if let Ok(audience) = env::var("MINDCLADE_AUDIENCE") {
        builder = builder.audience(audience);
    }
    Ok((builder.build()?, identity))
}

fn required_env(name: &str) -> Result<String, io::Error> {
    env::var(name).map_err(|_| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("required environment variable {name} is missing"),
        )
    })
}
