//! Terminal UI and progress formatters.

use is_terminal::IsTerminal;
use std::io::{self, BufRead, Write};
use std::time::Instant;

use crate::provisioning::ProvisioningError;
use crate::runtime_manifest::format_bytes;

pub fn format_duration(seconds: u64) -> String {
    if seconds < 60 {
        format!("{}s", seconds)
    } else {
        let minutes = seconds / 60;
        let remaining_seconds = seconds % 60;
        if minutes < 60 {
            format!("{}m {:02}s", minutes, remaining_seconds)
        } else {
            let hours = minutes / 60;
            let remaining_minutes = minutes % 60;
            format!("{}h {:02}m", hours, remaining_minutes)
        }
    }
}

pub struct TerminalUI {
    pub assume_yes: bool,
    last_download_percent: i32,
    last_model_percent: i32,
    last_update_percent: i32,
    download_started_at: Option<Instant>,
    download_started_bytes: u64,
    last_download_report_at: Option<Instant>,
}

impl TerminalUI {
    pub fn new(assume_yes: bool) -> Self {
        Self {
            assume_yes,
            last_download_percent: -1,
            last_model_percent: -1,
            last_update_percent: -1,
            download_started_at: None,
            download_started_bytes: 0,
            last_download_report_at: None,
        }
    }

    pub fn emit(&self, message: &str) {
        println!("[buddy] {}", message);
    }

    pub fn confirm(&self, message: &str, default: bool) -> Result<bool, ProvisioningError> {
        if self.assume_yes {
            self.emit(&format!("{} yes", message));
            return Ok(true);
        }

        if !io::stdin().is_terminal() {
            return Err(ProvisioningError::Cancelled(format!(
                "confirmation required: {} Run 'buddy setup --yes' for non-interactive setup.",
                message
            )));
        }

        let suffix = if default { "[Y/n]" } else { "[y/N]" };
        print!("{} {} ", message, suffix);
        io::stdout()
            .flush()
            .map_err(|e| ProvisioningError::Failure(e.to_string()))?;

        let mut input = String::new();
        let stdin = io::stdin();
        stdin
            .lock()
            .read_line(&mut input)
            .map_err(|e| ProvisioningError::Failure(e.to_string()))?;

        let trimmed = input.trim().to_ascii_lowercase();
        if trimmed.is_empty() {
            Ok(default)
        } else {
            Ok(trimmed == "y" || trimmed == "yes")
        }
    }

    pub fn download_progress(&mut self, completed: u64, total: Option<u64>) {
        let now = Instant::now();
        if self.download_started_at.is_none() {
            self.download_started_at = Some(now);
            self.download_started_bytes = completed;
        }

        if let Some(total_bytes) = total {
            let percent = ((completed as f64 * 100.0 / total_bytes as f64) as i32).min(100);
            let report_is_due = self
                .last_download_report_at
                .map(|t| now.duration_since(t).as_secs_f64() >= 1.0)
                .unwrap_or(true);

            if percent == self.last_download_percent && completed != total_bytes && !report_is_due {
                return;
            }

            self.last_download_percent = percent;
            self.last_download_report_at = Some(now);

            let mut message = format!(
                "Runtime download {}% ({} of {})",
                percent,
                format_bytes(completed),
                format_bytes(total_bytes)
            );

            let started_at = self.download_started_at.unwrap();
            let elapsed = now.duration_since(started_at).as_secs_f64();
            let transferred = completed.saturating_sub(self.download_started_bytes);

            if elapsed > 0.0 && transferred > 0 {
                let bytes_per_second = transferred as f64 / elapsed;
                let remaining = total_bytes.saturating_sub(completed);
                let eta_seconds = (remaining as f64 / bytes_per_second) as u64;
                message.push_str(&format!(
                    " at {}/s, ETA {}",
                    format_bytes(bytes_per_second as u64),
                    format_duration(eta_seconds)
                ));
            }

            self.emit(&message);
        } else if completed > 0 {
            let report_is_due = self
                .last_download_report_at
                .map(|t| now.duration_since(t).as_secs_f64() >= 1.0)
                .unwrap_or(true);

            if report_is_due {
                self.last_download_report_at = Some(now);
                self.emit(&format!("Runtime download {}", format_bytes(completed)));
            }
        }
    }

    pub fn model_progress(&mut self, status: &str, completed: Option<u64>, total: Option<u64>) {
        if let (Some(comp), Some(tot)) = (completed, total) {
            if tot > 0 {
                let percent = ((comp as f64 * 100.0 / tot as f64) as i32).min(100);
                if percent == self.last_model_percent {
                    return;
                }
                self.last_model_percent = percent;
                self.emit(&format!(
                    "Model download {}% ({} of {})",
                    percent,
                    format_bytes(comp),
                    format_bytes(tot)
                ));
            }
        } else if status == "pulling manifest"
            || status == "verifying sha256 digest"
            || status == "success"
        {
            self.emit(&format!("Model: {}", status));
        }
    }

    pub fn update_progress(&mut self, completed: u64, total: Option<u64>) {
        if let Some(tot) = total {
            if tot > 0 {
                let percent = ((completed as f64 * 100.0 / tot as f64) as i32).min(100);
                if percent == self.last_update_percent {
                    return;
                }
                self.last_update_percent = percent;
                self.emit(&format!(
                    "Update download {}% ({} of {})",
                    percent,
                    format_bytes(completed),
                    format_bytes(tot)
                ));
            }
        } else if completed > 0 {
            self.emit(&format!("Update download {}", format_bytes(completed)));
        }
    }
}
