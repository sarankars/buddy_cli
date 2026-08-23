//! Verified HTTP downloads with resumption and retry support.

use reqwest::blocking::Client;
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT_ENCODING, RANGE, USER_AGENT};
use reqwest::StatusCode;
use sha2::{Digest, Sha256};
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DownloadError(pub String);

impl fmt::Display for DownloadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for DownloadError {}

pub type DownloadProgress<'a> = Box<dyn FnMut(u64, Option<u64>) + 'a>;
pub type DownloadStatus<'a> = Box<dyn FnMut(&str) + 'a>;

const CHUNK_SIZE: usize = 64 * 1024;

pub fn sha256_file(path: &Path) -> Result<String, io::Error> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 1024 * 1024];

    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }

    Ok(hex::encode(hasher.finalize()))
}

fn digest_partial(path: &Path) -> (Sha256, u64) {
    let mut hasher = Sha256::new();
    let mut downloaded = 0u64;

    if path.exists() {
        if let Ok(mut file) = File::open(path) {
            let mut buffer = [0u8; 1024 * 1024];
            while let Ok(count) = file.read(&mut buffer) {
                if count == 0 {
                    break;
                }
                hasher.update(&buffer[..count]);
                downloaded += count as u64;
            }
        }
    }

    (hasher, downloaded)
}

pub struct DownloadOptions<'a> {
    pub timeout: Duration,
    pub max_attempts: usize,
    pub low_speed_limit: u64,
    pub low_speed_window: Duration,
    pub resume_command: &'static str,
    pub progress: Option<DownloadProgress<'a>>,
    pub status: Option<DownloadStatus<'a>>,
}

impl<'a> Default for DownloadOptions<'a> {
    fn default() -> Self {
        Self {
            timeout: Duration::from_secs(15),
            max_attempts: 4,
            low_speed_limit: 16 * 1024,
            low_speed_window: Duration::from_secs(30),
            resume_command: "buddy setup",
            progress: None,
            status: None,
        }
    }
}

pub fn download_verified(
    url: &str,
    destination: &Path,
    expected_sha256: &str,
    mut options: DownloadOptions,
) -> Result<PathBuf, DownloadError> {
    if options.max_attempts < 1 {
        return Err(DownloadError("max_attempts must be at least 1".to_string()));
    }

    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| DownloadError(format!("could not create directory: {}", e)))?;
    }

    let partial_file_name = format!(
        ".{}.part",
        destination
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("download")
    );
    let partial = destination.with_file_name(partial_file_name);

    let client = Client::builder()
        .timeout(options.timeout)
        .build()
        .map_err(|e| DownloadError(format!("could not build HTTP client: {}", e)))?;

    for attempt in 1..=options.max_attempts {
        let (mut hasher, mut resumed_at) = digest_partial(&partial);

        // If the partial file is already complete and matches the sha256
        if resumed_at > 0 {
            let partial_hex = hex::encode(hasher.clone().finalize());
            if partial_hex.eq_ignore_ascii_case(expected_sha256) {
                if let Some(ref mut p) = options.progress {
                    p(resumed_at, Some(resumed_at));
                }
                fs::rename(&partial, destination)
                    .map_err(|e| DownloadError(format!("could not move verified file: {}", e)))?;
                return Ok(destination.to_path_buf());
            }
        }

        let mut headers = HeaderMap::new();
        headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("identity"));
        headers.insert(
            USER_AGENT,
            HeaderValue::from_str(&format!("Buddy-CLI/{}", env!("CARGO_PKG_VERSION"))).unwrap(),
        );

        if resumed_at > 0 {
            if let Ok(val) = HeaderValue::from_str(&format!("bytes={}-", resumed_at)) {
                headers.insert(RANGE, val);
            }
            if let Some(ref mut s) = options.status {
                s(&format!("Resuming download from {} bytes", resumed_at));
            }
        }

        let request_res = client.get(url).headers(headers).send();

        let mut response = match request_res {
            Ok(resp) => resp,
            Err(e) => {
                if attempt == options.max_attempts {
                    return Err(DownloadError(format!(
                        "download stalled after {} attempts; run '{}' again to resume: {}",
                        options.max_attempts, options.resume_command, e
                    )));
                }
                let retry_delay = (1u64 << (attempt - 1)).min(4);
                if let Some(ref mut s) = options.status {
                    s(&format!(
                        "Download paused ({}). Retrying in {}s (attempt {}/{})",
                        e,
                        retry_delay,
                        attempt + 1,
                        options.max_attempts
                    ));
                }
                thread::sleep(Duration::from_secs(retry_delay));
                continue;
            }
        };

        let status = response.status();
        let is_range_response = status == StatusCode::PARTIAL_CONTENT;

        if resumed_at > 0 && !is_range_response {
            // Server did not accept Range header; start fresh
            hasher = Sha256::new();
            resumed_at = 0;
        }

        let total_size = if let Some(content_range) = response.headers().get("Content-Range") {
            if let Ok(range_str) = content_range.to_str() {
                if let Some((_, total_str)) = range_str.rsplit_once('/') {
                    if total_str != "*" {
                        total_str.parse::<u64>().ok()
                    } else {
                        None
                    }
                } else {
                    None
                }
            } else {
                None
            }
        } else {
            response
                .content_length()
                .map(|content_length| resumed_at + content_length)
        };

        let mut file = match if resumed_at > 0 {
            OpenOptions::new().create(true).append(true).open(&partial)
        } else {
            File::create(&partial)
        } {
            Ok(f) => f,
            Err(e) => return Err(DownloadError(format!("could not open file: {}", e))),
        };

        let mut downloaded = resumed_at;
        let attempt_started_at = Instant::now();

        if let Some(ref mut p) = options.progress {
            p(downloaded, total_size);
        }

        let mut buffer = [0u8; CHUNK_SIZE];
        let mut transfer_failed = false;

        loop {
            match response.read(&mut buffer) {
                Ok(0) => break,
                Ok(count) => {
                    if let Err(e) = file.write_all(&buffer[..count]) {
                        return Err(DownloadError(format!("write error: {}", e)));
                    }
                    hasher.update(&buffer[..count]);
                    downloaded += count as u64;

                    if let Some(ref mut p) = options.progress {
                        p(downloaded, total_size);
                    }

                    let attempt_elapsed = attempt_started_at.elapsed();
                    let transferred_this_attempt = downloaded - resumed_at;

                    if attempt < options.max_attempts && attempt_elapsed >= options.low_speed_window
                    {
                        let elapsed_secs = attempt_elapsed.as_secs_f64();
                        if elapsed_secs > 0.0
                            && (transferred_this_attempt as f64 / elapsed_secs)
                                < options.low_speed_limit as f64
                        {
                            transfer_failed = true;
                            break;
                        }
                    }
                }
                Err(_) => {
                    transfer_failed = true;
                    break;
                }
            }
        }

        let _ = file.flush();
        let _ = file.sync_all();

        if transfer_failed {
            if attempt == options.max_attempts {
                return Err(DownloadError(format!(
                    "download stalled after {} attempts; run '{}' again to resume",
                    options.max_attempts, options.resume_command
                )));
            }
            let retry_delay = (1u64 << (attempt - 1)).min(4);
            if let Some(ref mut s) = options.status {
                s(&format!(
                    "Download paused. Retrying in {}s (attempt {}/{})",
                    retry_delay,
                    attempt + 1,
                    options.max_attempts
                ));
            }
            thread::sleep(Duration::from_secs(retry_delay));
            continue;
        }

        let actual_sha256 = hex::encode(hasher.finalize());
        if !actual_sha256.eq_ignore_ascii_case(expected_sha256) {
            let _ = fs::remove_file(&partial);
            return Err(DownloadError(format!(
                "download checksum mismatch: expected {}, received {}",
                expected_sha256, actual_sha256
            )));
        }

        fs::rename(&partial, destination)
            .map_err(|e| DownloadError(format!("could not move verified file: {}", e)))?;
        return Ok(destination.to_path_buf());
    }

    Err(DownloadError("download did not complete".to_string()))
}
