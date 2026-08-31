use std::io::{self, Read, Write};

use prost::Message;
use protoc_gen_prost::GeneratorResultExt;

fn main() -> io::Result<()> {
    if std::env::args().any(|argument| argument == "--version") {
        println!("{}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }

    let mut request = Vec::new();
    io::stdin().read_to_end(&mut request)?;
    let response = protoc_gen_prost::execute(request.as_slice()).unwrap_codegen_response();
    let mut encoded = Vec::new();
    response
        .encode(&mut encoded)
        .expect("encode Prost code-generator response");
    io::stdout().write_all(&encoded)
}
