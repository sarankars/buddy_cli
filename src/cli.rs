//! Command-line interface for Buddy.

use clap::{Args, Parser, Subcommand};
use is_terminal::IsTerminal;
use std::cell::RefCell;
use std::io::{self, Read, Write};
use std::rc::Rc;

use crate::constants::DEFAULT_MODEL;
use crate::editor::read_prompt_from_editor;
use crate::enhancer::{OllamaEnhancer, RuleBasedEnhancer};
use crate::ollama::{GenerationProgress, OllamaClient};
use crate::provisioning::ProvisioningError;
use crate::services::{build_services, Services};
use crate::ui::TerminalUI;

#[derive(Parser, Debug)]
#[command(
    name = "buddy",
    about = "Enhance rough prompts before sending them to an AI assistant.",
    version = env!("CARGO_PKG_VERSION"),
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand, Debug)]
pub enum Commands {
    /// Provision and verify the local enhancement runtime.
    Setup(SetupArgs),
    /// Improve a rough prompt.
    Enhance(EnhanceArgs),
    /// Diagnose Buddy, Ollama, and the enhancement model.
    Doctor(DoctorArgs),
    /// Check for and install a newer Buddy release.
    Update(UpdateArgs),
}

#[derive(Args, Debug)]
pub struct SetupArgs {
    /// Accept required runtime and model downloads.
    #[arg(long)]
    pub yes: bool,

    /// Show the setup plan without changing anything.
    #[arg(long)]
    pub dry_run: bool,

    /// Ollama model to provision.
    #[arg(long, default_value = DEFAULT_MODEL)]
    pub model: String,
}

#[derive(Args, Debug)]
pub struct EnhanceArgs {
    /// Prompt to enhance. When omitted, Buddy reads piped standard input or opens a text editor on an interactive terminal.
    #[arg(trailing_var_arg = true)]
    pub prompt: Vec<String>,

    /// Use the deterministic enhancer without Ollama.
    #[arg(long)]
    pub offline: bool,
}

#[derive(Args, Debug)]
pub struct DoctorArgs {
    /// Return the diagnostic report as JSON.
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct UpdateArgs {
    /// Check for an update without downloading or installing it.
    #[arg(long, conflicts_with = "yes")]
    pub check: bool,

    /// Install an available update without asking for confirmation.
    #[arg(long, conflicts_with = "check")]
    pub yes: bool,
}

fn read_prompt(parts: &[String]) -> Result<String, String> {
    let prompt = if !parts.is_empty() {
        parts.join(" ")
    } else if io::stdin().is_terminal() {
        read_prompt_from_editor().map_err(|e| e.to_string())?
    } else {
        let mut buffer = String::new();
        io::stdin()
            .read_to_string(&mut buffer)
            .map_err(|e| e.to_string())?;
        buffer
    };

    let trimmed = prompt.trim();
    if trimmed.is_empty() {
        return Err("the prompt cannot be empty".to_string());
    }

    Ok(trimmed.to_string())
}

fn run_setup(args: SetupArgs, services: &Services) -> i32 {
    if args.dry_run {
        println!("Buddy setup plan:");
        for (index, message) in services.provisioner.plan(&args.model).iter().enumerate() {
            println!("  {}. {}", index + 1, message);
        }
        return 0;
    }

    let ui = Rc::new(RefCell::new(TerminalUI::new(args.yes)));
    let ui_confirm = ui.clone();
    let ui_emit = ui.clone();
    let ui_download = ui.clone();
    let ui_model = ui.clone();

    let setup_result = services.provisioner.setup(
        &args.model,
        Box::new(move |msg, def| ui_confirm.borrow_mut().confirm(msg, def)),
        Box::new(move |msg| ui_emit.borrow().emit(msg)),
        Some(Box::new(move |comp, tot| {
            ui_download.borrow_mut().download_progress(comp, tot)
        })),
        Some(Box::new(move |status, comp, tot| {
            ui_model.borrow_mut().model_progress(status, comp, tot)
        })),
    );

    match setup_result {
        Ok(_) => {
            ui.borrow().emit("Buddy is ready");
            0
        }
        Err(e) => {
            if let Some(ProvisioningError::Cancelled(msg)) = e.downcast_ref::<ProvisioningError>() {
                eprintln!("buddy: setup cancelled: {}", msg);
                2
            } else {
                eprintln!("buddy: setup failed: {}", e);
                eprintln!("Run 'buddy doctor' for diagnostics.");
                1
            }
        }
    }
}

fn offer_first_run_setup(services: &Services) -> bool {
    let ui = Rc::new(RefCell::new(TerminalUI::new(false)));
    let proceed = ui
        .borrow_mut()
        .confirm("Buddy is not configured. Run automatic setup now?", true)
        .unwrap_or_default();

    if !proceed {
        return false;
    }

    let ui_confirm = ui.clone();
    let ui_emit = ui.clone();
    let ui_download = ui.clone();
    let ui_model = ui.clone();

    let res = services.provisioner.setup(
        DEFAULT_MODEL,
        Box::new(move |msg, def| ui_confirm.borrow_mut().confirm(msg, def)),
        Box::new(move |msg| ui_emit.borrow().emit(msg)),
        Some(Box::new(move |comp, tot| {
            ui_download.borrow_mut().download_progress(comp, tot)
        })),
        Some(Box::new(move |status, comp, tot| {
            ui_model.borrow_mut().model_progress(status, comp, tot)
        })),
    );

    if res.is_ok() {
        ui.borrow().emit("Buddy is ready");
        true
    } else {
        if let Err(e) = res {
            eprintln!("buddy: automatic setup did not complete: {}", e);
        }
        false
    }
}

fn run_enhance(args: EnhanceArgs, services: &Services) -> i32 {
    let prompt = match read_prompt(&args.prompt) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("buddy: error: {}", e);
            return 2;
        }
    };

    if args.offline {
        let enhanced = RuleBasedEnhancer::new().enhance(&prompt).unwrap_or(prompt);
        println!("{}", enhanced);
        return 0;
    }

    let mut config = services.config_store.load().unwrap_or(None);

    if config.is_none() && offer_first_run_setup(services) {
        config = services.config_store.load().unwrap_or(None);
    }

    if let Some(ref cfg) = config {
        let selection = services.runtime_manager.selection_from_config(cfg);
        if let Err(e) = services.runtime_manager.start(&selection) {
            eprintln!(
                "buddy: local AI unavailable ({}); using offline enhancer",
                e
            );
        } else {
            match OllamaClient::new(&cfg.base_url) {
                Ok(client) => {
                    let enhancer = OllamaEnhancer::new(client, &cfg.model);
                    let progress = Box::new(|chunk: &str| {
                        eprint!("{}", chunk);
                        let _ = io::stderr().flush();
                    }) as GenerationProgress;
                    let result = enhancer.enhance_with_progress(&prompt, Some(progress));
                    eprintln!();
                    match result {
                        Ok(enhanced) => {
                            println!("{}", enhanced);
                            return 0;
                        }
                        Err(e) => {
                            eprintln!(
                                "buddy: local AI unavailable ({}); using offline enhancer",
                                e
                            );
                        }
                    }
                }
                Err(e) => {
                    eprintln!(
                        "buddy: local AI unavailable ({}); using offline enhancer",
                        e
                    );
                }
            }
        }
    }

    if config.is_none() {
        eprintln!(
            "buddy: local AI is not configured; using offline enhancer. Run 'buddy setup' to enable AI enhancement."
        );
    }

    let fallback = RuleBasedEnhancer::new().enhance(&prompt).unwrap_or(prompt);
    println!("{}", fallback);
    0
}

fn run_doctor(args: DoctorArgs, services: &Services) -> i32 {
    let report = services.doctor.run();
    if args.json {
        if let Ok(json_str) = serde_json::to_string_pretty(&report) {
            println!("{}", json_str);
        }
    } else {
        for check in &report.checks {
            println!("[{}] {}: {}", check.status, check.name, check.detail);
        }
        if report.healthy {
            println!("Buddy is ready.");
        } else {
            println!("Buddy needs attention.");
        }
    }

    if report.healthy {
        0
    } else {
        1
    }
}

fn run_update(args: UpdateArgs, services: &Services) -> i32 {
    let ui = Rc::new(RefCell::new(TerminalUI::new(args.yes)));
    let info = match services.updater.check() {
        Ok(inf) => inf,
        Err(e) => {
            eprintln!("buddy: update check failed: {}", e);
            return 1;
        }
    };

    if info.current_is_newer() {
        ui.borrow().emit(&format!(
            "Buddy {} is newer than the latest stable release ({})",
            info.current_version, info.latest_version
        ));
        return 0;
    }

    if !info.update_available() {
        ui.borrow()
            .emit(&format!("Buddy {} is up to date", info.current_version));
        return 0;
    }

    ui.borrow().emit(&format!(
        "Buddy {} is available (current: {})",
        info.latest_version, info.current_version
    ));
    ui.borrow().emit(&format!("Release: {}", info.release_url));

    if args.check {
        return 0;
    }

    if !args.yes {
        if !io::stdin().is_terminal() {
            eprintln!(
                "buddy: update requires confirmation; rerun with 'buddy update --yes' in non-interactive environments"
            );
            return 2;
        }

        match ui
            .borrow_mut()
            .confirm(&format!("Install Buddy {}?", info.latest_version), false)
        {
            Ok(true) => {}
            Ok(false) => {
                ui.borrow().emit("Update cancelled");
                return 0;
            }
            Err(e) => {
                eprintln!("buddy: update cancelled: {}", e);
                return 2;
            }
        }
    }

    let ui_update = ui.clone();
    let ui_emit = ui.clone();

    match services.updater.install(
        &info,
        Some(Box::new(move |comp, tot| {
            ui_update.borrow_mut().update_progress(comp, tot)
        })),
        Some(Box::new(move |msg| ui_emit.borrow().emit(msg))),
    ) {
        Ok(outcome) => {
            ui.borrow().emit(&outcome.message);
            0
        }
        Err(e) => {
            eprintln!("buddy: update failed: {}", e);
            1
        }
    }
}

pub fn run_cli_with_args<I, T>(args: I, services: &Services) -> i32
where
    I: IntoIterator<Item = T>,
    T: Into<std::ffi::OsString> + Clone,
{
    match Cli::try_parse_from(args) {
        Ok(cli) => match cli.command {
            Commands::Setup(setup_args) => run_setup(setup_args, services),
            Commands::Enhance(enhance_args) => run_enhance(enhance_args, services),
            Commands::Doctor(doctor_args) => run_doctor(doctor_args, services),
            Commands::Update(update_args) => run_update(update_args, services),
        },
        Err(e) => {
            let _ = e.print();
            if e.use_stderr() {
                2
            } else {
                0
            }
        }
    }
}

pub fn main() -> i32 {
    let services = build_services();
    run_cli_with_args(std::env::args(), &services)
}
