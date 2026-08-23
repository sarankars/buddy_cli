//! Secure update discovery and installation for standalone Buddy releases.

use regex::Regex;
use reqwest::blocking::Client;
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, USER_AGENT};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::fmt;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::LazyLock;
use std::time::Duration;
use tempfile::NamedTempFile;

use crate::archive::extract_archive;
use crate::download::{download_verified, DownloadOptions, DownloadProgress, DownloadStatus};
use crate::paths::AppPaths;
use crate::runtime_manifest::{normalize_architecture, normalize_operating_system};

const REPOSITORY: &str = "sarankars/buddy_cli";
const LATEST_RELEASE_API: &str = "https://api.github.com/repos/sarankars/buddy_cli/releases/latest";
const GITHUB_API_VERSION: &str = "2026-03-10";
const MAX_API_RESPONSE: usize = 2 * 1024 * 1024;
const MAX_CHECKSUM_RESPONSE: usize = 4096;

static VERSION_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$").unwrap());

static CHECKSUM_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^([0-9a-f]{64})  ([A-Za-z0-9._-]+)\r?\n?$").unwrap());

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateError(pub String);

impl fmt::Display for UpdateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for UpdateError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReleaseAsset {
    pub name: String,
    pub download_url: String,
    pub size: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub digest: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateInfo {
    pub current_version: String,
    pub latest_version: String,
    pub release_url: String,
    pub package: ReleaseAsset,
    pub checksum: ReleaseAsset,
    pub archive_type: String,
}

impl UpdateInfo {
    pub fn update_available(&self) -> bool {
        parse_version_tuple(&self.latest_version) > parse_version_tuple(&self.current_version)
    }

    pub fn current_is_newer(&self) -> bool {
        parse_version_tuple(&self.current_version) > parse_version_tuple(&self.latest_version)
    }
}

fn parse_version_tuple(version: &str) -> (u64, u64, u64) {
    if let Some(caps) = VERSION_PATTERN.captures(version) {
        let major = caps.get(1).unwrap().as_str().parse::<u64>().unwrap_or(0);
        let minor = caps.get(2).unwrap().as_str().parse::<u64>().unwrap_or(0);
        let patch = caps.get(3).unwrap().as_str().parse::<u64>().unwrap_or(0);
        (major, minor, patch)
    } else {
        (0, 0, 0)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateOutcome {
    pub message: String,
    pub restart_required: bool,
}

pub fn release_package(
    platform_name: &str,
    machine: &str,
) -> Result<(&'static str, &'static str, &'static str), UpdateError> {
    let os = normalize_operating_system(platform_name);
    let arch = normalize_architecture(machine);

    let release_arch = match arch.as_str() {
        "amd64" => "x64",
        "arm64" => "arm64",
        _ => {
            return Err(UpdateError(format!(
                "Buddy updates are not available for architecture {}",
                arch
            )))
        }
    };

    match os.as_str() {
        "darwin" => match release_arch {
            "x64" => Ok(("buddy-macos-x64.pkg", "pkg", "darwin")),
            "arm64" => Ok(("buddy-macos-arm64.pkg", "pkg", "darwin")),
            _ => unreachable!(),
        },
        "windows" => match release_arch {
            "x64" => Ok(("buddy-windows-x64.zip", "zip", "windows")),
            "arm64" => Ok(("buddy-windows-arm64.zip", "zip", "windows")),
            _ => unreachable!(),
        },
        "linux" => match release_arch {
            "x64" => Ok(("buddy-linux-x64.tar.gz", "tgz", "linux")),
            "arm64" => Ok(("buddy-linux-arm64.tar.gz", "tgz", "linux")),
            _ => unreachable!(),
        },
        _ => Err(UpdateError(format!(
            "Buddy updates are not available for {}",
            os
        ))),
    }
}

fn asset_from_json(value: &Value, tag: &str) -> Result<ReleaseAsset, UpdateError> {
    let obj = value
        .as_object()
        .ok_or_else(|| UpdateError("GitHub returned invalid release asset metadata".to_string()))?;

    let name = obj.get("name").and_then(|v| v.as_str()).ok_or_else(|| {
        UpdateError("GitHub returned incomplete release asset metadata".to_string())
    })?;

    let download_url = obj
        .get("browser_download_url")
        .and_then(|v| v.as_str())
        .ok_or_else(|| {
            UpdateError("GitHub returned incomplete release asset metadata".to_string())
        })?;

    let size = obj.get("size").and_then(|v| v.as_u64()).ok_or_else(|| {
        UpdateError("GitHub returned incomplete release asset metadata".to_string())
    })?;

    let state = obj.get("state").and_then(|v| v.as_str()).unwrap_or("");
    if state != "uploaded" || size < 1 {
        return Err(UpdateError(
            "GitHub returned incomplete release asset metadata".to_string(),
        ));
    }

    let expected_url = format!(
        "https://github.com/{}/releases/download/{}/{}",
        REPOSITORY, tag, name
    );
    if download_url != expected_url {
        return Err(UpdateError(format!(
            "release asset has an untrusted download URL: {}",
            name
        )));
    }

    let digest = obj
        .get("digest")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    Ok(ReleaseAsset {
        name: name.to_string(),
        download_url: download_url.to_string(),
        size,
        digest,
    })
}

fn extract_binary(
    archive: &Path,
    destination: &Path,
    archive_type: &str,
) -> Result<(), UpdateError> {
    let temp_extract_dir = tempfile::tempdir()
        .map_err(|e| UpdateError(format!("could not create staging directory: {}", e)))?;

    extract_archive(archive, temp_extract_dir.path(), archive_type)
        .map_err(|e| UpdateError(format!("could not extract update archive: {}", e)))?;

    let expected_name = if archive_type == "zip" {
        "buddy.exe"
    } else {
        "buddy"
    };
    let candidate = temp_extract_dir.path().join(expected_name);

    if !candidate.is_file() {
        return Err(UpdateError(
            "update archive does not contain exactly one Buddy executable".to_string(),
        ));
    }

    if let Some(parent) = destination.parent() {
        let _ = fs::create_dir_all(parent);
    }

    fs::copy(&candidate, destination)
        .map_err(|e| UpdateError(format!("could not stage extracted executable: {}", e)))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(destination) {
            let mut perms = meta.permissions();
            perms.set_mode(perms.mode() | 0o755);
            let _ = fs::set_permissions(destination, perms);
        }
    }

    Ok(())
}

pub struct Updater {
    pub paths: AppPaths,
    pub current_version: String,
    pub platform_name: String,
    pub machine: String,
    pub executable: PathBuf,
    pub mac_install_path: PathBuf,
}

impl Updater {
    pub fn new(paths: AppPaths) -> Self {
        let current_version = env!("CARGO_PKG_VERSION").to_string();
        let platform_name = if cfg!(target_os = "macos") {
            "darwin".to_string()
        } else if cfg!(target_os = "windows") {
            "win32".to_string()
        } else {
            "linux".to_string()
        };

        let machine = env::consts::ARCH.to_string();
        let executable = env::current_exe().unwrap_or_else(|_| PathBuf::from("buddy"));
        let mac_install_path = PathBuf::from("/usr/local/bin/buddy");

        Self {
            paths,
            current_version,
            platform_name,
            machine,
            executable,
            mac_install_path,
        }
    }

    fn read_url(&self, url: &str, accept: &str, limit: usize) -> Result<Vec<u8>, UpdateError> {
        let mut headers = HeaderMap::new();
        headers.insert(ACCEPT, HeaderValue::from_str(accept).unwrap());
        headers.insert(
            USER_AGENT,
            HeaderValue::from_str(&format!("Buddy-CLI/{}", self.current_version)).unwrap(),
        );
        headers.insert(
            "X-GitHub-Api-Version",
            HeaderValue::from_static(GITHUB_API_VERSION),
        );

        let client = Client::builder()
            .timeout(Duration::from_secs(15))
            .build()
            .map_err(|e| UpdateError(format!("HTTP client error: {}", e)))?;

        let resp =
            client.get(url).headers(headers).send().map_err(|e| {
                UpdateError(format!("could not retrieve update information: {}", e))
            })?;

        if !resp.status().is_success() {
            return Err(UpdateError(format!(
                "could not retrieve update information: HTTP {}",
                resp.status()
            )));
        }

        let mut buf = Vec::new();
        let mut take = resp.take(limit as u64 + 1);
        take.read_to_end(&mut buf)
            .map_err(|e| UpdateError(format!("read error: {}", e)))?;

        if buf.len() > limit {
            return Err(UpdateError(
                "update information exceeded the safe size limit".to_string(),
            ));
        }

        Ok(buf)
    }

    pub fn check(&self) -> Result<UpdateInfo, UpdateError> {
        let raw = self.read_url(
            LATEST_RELEASE_API,
            "application/vnd.github+json",
            MAX_API_RESPONSE,
        )?;

        let value: Value = serde_json::from_slice(&raw).map_err(|e| {
            UpdateError(format!(
                "GitHub returned invalid release information: {}",
                e
            ))
        })?;

        let tag = value
            .get("tag_name")
            .and_then(|v| v.as_str())
            .ok_or_else(|| UpdateError("GitHub release missing tag_name".to_string()))?;

        if !tag.starts_with('v') || !VERSION_PATTERN.is_match(&tag[1..]) {
            return Err(UpdateError(
                "GitHub's latest release metadata is not a stable release".to_string(),
            ));
        }

        let draft = value
            .get("draft")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let prerelease = value
            .get("prerelease")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        if draft || prerelease {
            return Err(UpdateError(
                "GitHub's latest release metadata is not a stable release".to_string(),
            ));
        }

        let release_url = value
            .get("html_url")
            .and_then(|v| v.as_str())
            .ok_or_else(|| UpdateError("missing html_url".to_string()))?;

        let expected_release_url =
            format!("https://github.com/{}/releases/tag/{}", REPOSITORY, tag);
        if release_url != expected_release_url {
            return Err(UpdateError(
                "GitHub returned an untrusted release URL".to_string(),
            ));
        }

        let (package_name, archive_type, _) = release_package(&self.platform_name, &self.machine)?;
        let checksum_name = format!("{}.sha256", package_name);

        let raw_assets = value
            .get("assets")
            .and_then(|v| v.as_array())
            .ok_or_else(|| {
                UpdateError("GitHub release does not contain an asset list".to_string())
            })?;

        let mut assets = std::collections::HashMap::new();
        for raw_asset in raw_assets {
            let asset = asset_from_json(raw_asset, tag)?;
            if assets.contains_key(&asset.name) {
                return Err(UpdateError(format!(
                    "GitHub release contains duplicate asset {}",
                    asset.name
                )));
            }
            assets.insert(asset.name.clone(), asset);
        }

        let package = assets
            .get(package_name)
            .cloned()
            .ok_or_else(|| UpdateError(format!("GitHub release is missing {}", package_name)))?;

        let checksum = assets
            .get(&checksum_name)
            .cloned()
            .ok_or_else(|| UpdateError(format!("GitHub release is missing {}", checksum_name)))?;

        Ok(UpdateInfo {
            current_version: self.current_version.clone(),
            latest_version: tag[1..].to_string(),
            release_url: release_url.to_string(),
            package,
            checksum,
            archive_type: archive_type.to_string(),
        })
    }

    fn expected_checksum(&self, info: &UpdateInfo) -> Result<String, UpdateError> {
        let raw = self.read_url(
            &info.checksum.download_url,
            "application/octet-stream",
            MAX_CHECKSUM_RESPONSE,
        )?;

        let text = String::from_utf8(raw)
            .map_err(|_| UpdateError("release checksum is not ASCII text".to_string()))?;

        let caps = CHECKSUM_PATTERN
            .captures(&text)
            .ok_or_else(|| UpdateError("release checksum file has invalid contents".to_string()))?;

        let sha = caps.get(1).unwrap().as_str().to_string();
        let filename = caps.get(2).unwrap().as_str();

        if filename != info.package.name {
            return Err(UpdateError(
                "release checksum file has invalid contents".to_string(),
            ));
        }

        if let Some(ref digest) = info.package.digest {
            if digest != &format!("sha256:{}", sha) {
                return Err(UpdateError(
                    "release checksum does not match GitHub's asset digest".to_string(),
                ));
            }
        }

        Ok(sha)
    }

    fn smoke_test(&self, binary: &Path, version: &str) -> Result<(), UpdateError> {
        let output = Command::new(binary)
            .arg("--version")
            .output()
            .map_err(|e| {
                UpdateError(format!("downloaded Buddy executable could not run: {}", e))
            })?;

        let expected = format!("buddy {}", version);
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();

        if !output.status.success() || stdout != expected {
            return Err(UpdateError(
                "downloaded Buddy executable failed its version smoke test".to_string(),
            ));
        }

        Ok(())
    }

    fn install_linux(
        &self,
        staged: &Path,
        current: &Path,
        version: &str,
    ) -> Result<UpdateOutcome, UpdateError> {
        self.smoke_test(staged, version)?;

        let temp_file = NamedTempFile::new_in(
            current.parent().unwrap_or(Path::new(".")),
        )
        .map_err(|e| {
            UpdateError(format!(
                "could not replace {}: {}; reinstall Buddy in a writable location or run the update with sufficient permissions",
                current.display(), e
            ))
        })?;

        fs::copy(staged, temp_file.path())
            .map_err(|e| UpdateError(format!("could not copy update: {}", e)))?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(temp_file.path(), fs::Permissions::from_mode(0o755));
        }

        temp_file.persist(current).map_err(|e| {
            UpdateError(format!(
                "could not atomically replace {}: {}",
                current.display(),
                e
            ))
        })?;

        Ok(UpdateOutcome {
            message: format!(
                "Buddy was updated to {}. Restart Buddy to use the new version.",
                version
            ),
            restart_required: true,
        })
    }

    fn install_windows(
        &self,
        staged: &Path,
        current: &Path,
        version: &str,
    ) -> Result<UpdateOutcome, UpdateError> {
        self.smoke_test(staged, version)?;

        let script = staged.with_file_name("finish-buddy-update.ps1");
        fs::write(
            &script,
            "param([int]$BuddyPid, [string]$Source, [string]$Target)\n\
             $ErrorActionPreference = 'Stop'\n\
             Wait-Process -Id $BuddyPid -ErrorAction SilentlyContinue\n\
             Move-Item -LiteralPath $Source -Destination $Target -Force\n\
             Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue\n",
        )
        .map_err(|e| UpdateError(format!("could not write update script: {}", e)))?;

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
            const DETACHED_PROCESS: u32 = 0x00000008;
            let pid = std::process::id();

            let mut cmd = Command::new("powershell.exe");
            cmd.args([
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                &script.to_string_lossy(),
                "-BuddyPid",
                &pid.to_string(),
                "-Source",
                &staged.to_string_lossy(),
                "-Target",
                &current.to_string_lossy(),
            ]);
            cmd.creation_flags(CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS);

            cmd.spawn().map_err(|e| {
                UpdateError(format!("could not schedule the Windows update: {}", e))
            })?;
        }

        #[cfg(not(windows))]
        {
            let _ = current;
        }

        Ok(UpdateOutcome {
            message: format!(
                "Buddy {} is staged and will finish installing after this command exits. Start Buddy again in a few seconds.",
                version
            ),
            restart_required: true,
        })
    }

    fn install_macos(&self, package: &Path, version: &str) -> Result<UpdateOutcome, UpdateError> {
        if !package.is_file() {
            return Err(UpdateError(format!(
                "the macOS installer package was not found at {}",
                package.display()
            )));
        }

        let sig_output = Command::new("/usr/sbin/pkgutil")
            .arg("--check-signature")
            .arg(package)
            .output()
            .map_err(|e| UpdateError(format!("could not verify the macOS installer: {}", e)))?;

        if !sig_output.status.success() {
            return Err(UpdateError(
                "the macOS installer signature is invalid".to_string(),
            ));
        }

        let assess_output = Command::new("/usr/sbin/spctl")
            .args(["--assess", "--type", "install", "--verbose=2"])
            .arg(package)
            .output()
            .map_err(|e| UpdateError(format!("could not assess the macOS installer: {}", e)))?;

        if !assess_output.status.success() {
            return Err(UpdateError(
                "macOS Gatekeeper rejected the update installer".to_string(),
            ));
        }

        let installer_output = Command::new("/usr/sbin/installer")
            .args(["-pkg"])
            .arg(package)
            .args(["-target", "/"])
            .output()
            .map_err(|e| UpdateError(format!("could not run the macOS installer: {}", e)))?;

        if !installer_output.status.success() {
            let detail = String::from_utf8_lossy(&installer_output.stderr)
                .trim()
                .to_string();
            let suffix = if detail.is_empty() {
                String::new()
            } else {
                format!(": {}", detail)
            };
            return Err(UpdateError(format!(
                "the macOS installer exited unsuccessfully{}",
                suffix
            )));
        }

        self.smoke_test(&self.mac_install_path, version)?;

        Ok(UpdateOutcome {
            message: format!(
                "Buddy was updated to {} at {}.",
                version,
                self.mac_install_path.display()
            ),
            restart_required: true,
        })
    }

    pub fn install<'a>(
        &self,
        info: &UpdateInfo,
        download_progress: Option<DownloadProgress<'a>>,
        status: Option<DownloadStatus<'a>>,
    ) -> Result<UpdateOutcome, UpdateError> {
        if !info.update_available() {
            return Err(UpdateError(
                "the selected release is not newer than this Buddy version".to_string(),
            ));
        }

        let expected_checksum = self.expected_checksum(info)?;
        let update_dir = self
            .paths
            .updates_dir()
            .join(format!("v{}", info.latest_version));
        let _ = fs::create_dir_all(&update_dir);

        let package = update_dir.join(&info.package.name);

        let download_opts = DownloadOptions {
            progress: download_progress,
            status,
            resume_command: "buddy update",
            ..Default::default()
        };

        download_verified(
            &info.package.download_url,
            &package,
            &expected_checksum,
            download_opts,
        )
        .map_err(|e| UpdateError(format!("could not download the Buddy update: {}", e)))?;

        let (_, _, os) = release_package(&self.platform_name, &self.machine)?;
        match os {
            "darwin" => self.install_macos(&package, &info.latest_version),
            "windows" => {
                let staged = update_dir.join("new-buddy.exe");
                extract_binary(&package, &staged, &info.archive_type)?;
                self.install_windows(&staged, &self.executable, &info.latest_version)
            }
            _ => {
                let staged = update_dir.join("new-buddy");
                extract_binary(&package, &staged, &info.archive_type)?;
                self.install_linux(&staged, &self.executable, &info.latest_version)
            }
        }
    }
}
