//! Buddy CLI main executable entrypoint.

fn main() {
    let exit_code = buddy::cli::main();
    std::process::exit(exit_code);
}
