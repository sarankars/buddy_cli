//! Pinned Ollama runtime artifacts supported by Buddy.

use std::env;
use std::fmt;

use crate::constants::OLLAMA_RUNTIME_VERSION;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnsupportedPlatformError(pub String);

impl fmt::Display for UnsupportedPlatformError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for UnsupportedPlatformError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeSpec {
    pub operating_system: &'static str,
    pub architecture: &'static str,
    pub asset_name: &'static str,
    pub sha256: &'static str,
    pub size: u64,
    pub archive_type: &'static str,
    pub version: &'static str,
}

impl RuntimeSpec {
    pub fn url(&self) -> String {
        format!(
            "https://github.com/ollama/ollama/releases/download/v{}/{}",
            self.version, self.asset_name
        )
    }

    pub fn installation_name(&self) -> String {
        format!(
            "ollama-{}-{}-{}",
            self.version, self.operating_system, self.architecture
        )
    }
}

pub fn normalize_operating_system(value: &str) -> String {
    let lowered = value.to_ascii_lowercase();
    if lowered == "win32" || lowered == "windows" || lowered.starts_with("win") {
        "windows".to_string()
    } else if lowered.starts_with("darwin") || lowered.starts_with("mac") {
        "darwin".to_string()
    } else if lowered.starts_with("linux") {
        "linux".to_string()
    } else {
        lowered
    }
}

pub fn normalize_architecture(value: &str) -> String {
    let lowered = value.to_ascii_lowercase();
    if lowered == "x86_64" || lowered == "x64" || lowered == "amd64" {
        "amd64".to_string()
    } else if lowered == "aarch64" || lowered == "arm64" {
        "arm64".to_string()
    } else {
        lowered
    }
}

pub fn resolve_runtime_spec() -> Result<RuntimeSpec, UnsupportedPlatformError> {
    let os = if cfg!(target_os = "macos") {
        "darwin"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    };

    let arch = if cfg!(target_arch = "x86_64") {
        "amd64"
    } else if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        env::consts::ARCH
    };

    resolve_runtime_spec_for(Some(os), Some(arch))
}

pub fn resolve_runtime_spec_for(
    platform_name: Option<&str>,
    machine: Option<&str>,
) -> Result<RuntimeSpec, UnsupportedPlatformError> {
    let os = normalize_operating_system(platform_name.unwrap_or(if cfg!(target_os = "macos") {
        "darwin"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }));

    let arch = normalize_architecture(machine.unwrap_or(if cfg!(target_arch = "x86_64") {
        "amd64"
    } else if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        env::consts::ARCH
    }));

    match (os.as_str(), arch.as_str()) {
        ("darwin", "arm64") | ("darwin", "amd64") => Ok(RuntimeSpec {
            operating_system: "darwin",
            architecture: if arch == "arm64" { "arm64" } else { "amd64" },
            asset_name: "ollama-darwin.tgz",
            sha256: "5789dd037a86adb328c72c11fc45e6c558452d07e5b50814a8bdb7b0fbdbcd81",
            size: 145_747_028,
            archive_type: "tgz",
            version: OLLAMA_RUNTIME_VERSION,
        }),
        ("linux", "amd64") => Ok(RuntimeSpec {
            operating_system: "linux",
            architecture: "amd64",
            asset_name: "ollama-linux-amd64.tar.zst",
            sha256: "f7d6bdbcf71b83aa8670c4e7dc4b6936c0952fcf8b114eaf6a11cbadb9684214",
            size: 1_422_353_729,
            archive_type: "tar.zst",
            version: OLLAMA_RUNTIME_VERSION,
        }),
        ("linux", "arm64") => Ok(RuntimeSpec {
            operating_system: "linux",
            architecture: "arm64",
            asset_name: "ollama-linux-arm64.tar.zst",
            sha256: "aa7e06b5683ee66c4a3ec68ea7236db43b5a5d0821f0dfe2c5a215f4462bddf4",
            size: 1_542_011_985,
            archive_type: "tar.zst",
            version: OLLAMA_RUNTIME_VERSION,
        }),
        ("windows", "amd64") => Ok(RuntimeSpec {
            operating_system: "windows",
            architecture: "amd64",
            asset_name: "ollama-windows-amd64.zip",
            sha256: "7c941ae084569d298062d29f8139163a3187c76dbca0479c70d085e78fd8c7bb",
            size: 1_457_824_795,
            archive_type: "zip",
            version: OLLAMA_RUNTIME_VERSION,
        }),
        ("windows", "arm64") => Ok(RuntimeSpec {
            operating_system: "windows",
            architecture: "arm64",
            asset_name: "ollama-windows-arm64.zip",
            sha256: "f7cf76916c24550033500a92fb56b3ce3d225f3d7cde0ce0438e62696b34507a",
            size: 209_422_558,
            archive_type: "zip",
            version: OLLAMA_RUNTIME_VERSION,
        }),
        _ => Err(UnsupportedPlatformError(format!(
            "managed Ollama is not available for {}/{}",
            os, arch
        ))),
    }
}

pub fn format_bytes(value: u64) -> String {
    let mut size = value as f64;
    let units = ["B", "KB", "MB", "GB", "TB"];
    for (i, unit) in units.iter().enumerate() {
        if size < 1000.0 || *unit == "TB" {
            if i == 0 {
                return format!("{} B", value);
            } else {
                return format!("{:.1} {}", size, unit);
            }
        }
        size /= 1000.0;
    }
    format!("{:.1} TB", size)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_bytes() {
        assert_eq!(format_bytes(0), "0 B");
        assert_eq!(format_bytes(500), "500 B");
        assert_eq!(format_bytes(1000), "1.0 KB");
        assert_eq!(format_bytes(1_500_000), "1.5 MB");
        assert_eq!(format_bytes(1_900_000_000), "1.9 GB");
    }

    #[test]
    fn test_specs_resolution() {
        let mac_arm = resolve_runtime_spec_for(Some("darwin"), Some("arm64")).unwrap();
        assert_eq!(mac_arm.asset_name, "ollama-darwin.tgz");
        assert_eq!(mac_arm.archive_type, "tgz");

        let linux_x64 = resolve_runtime_spec_for(Some("linux"), Some("x86_64")).unwrap();
        assert_eq!(linux_x64.asset_name, "ollama-linux-amd64.tar.zst");
        assert_eq!(linux_x64.archive_type, "tar.zst");

        let win_arm = resolve_runtime_spec_for(Some("win32"), Some("aarch64")).unwrap();
        assert_eq!(win_arm.asset_name, "ollama-windows-arm64.zip");
        assert_eq!(win_arm.archive_type, "zip");

        let unsupported = resolve_runtime_spec_for(Some("freebsd"), Some("x86_64"));
        assert!(unsupported.is_err());
    }
}
