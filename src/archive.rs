//! Safe extraction for pinned runtime archives.

use flate2::read::GzDecoder;
use std::fmt;
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};
use tar::{Archive as TarArchive, EntryType};
use zip::ZipArchive;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArchiveError(pub String);

impl fmt::Display for ArchiveError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for ArchiveError {}

fn safe_member_path(root: &Path, member_name: &str) -> Result<PathBuf, ArchiveError> {
    let normalized = member_name.replace('\\', "/");
    let path = Path::new(&normalized);

    for component in path.components() {
        match component {
            Component::Prefix(_) | Component::RootDir | Component::ParentDir => {
                return Err(ArchiveError(format!(
                    "archive contains an unsafe path: {}",
                    member_name
                )));
            }
            Component::Normal(comp) => {
                if let Some(comp_str) = comp.to_str() {
                    if comp_str.contains(':') {
                        return Err(ArchiveError(format!(
                            "archive contains an unsafe path: {}",
                            member_name
                        )));
                    }
                }
            }
            Component::CurDir => {}
        }
    }

    let root_resolved = root
        .canonicalize()
        .unwrap_or_else(|_| normalize_path_simple(root));

    let target = root_resolved.join(path);
    let normalized_target = normalize_path_simple(&target);

    if !normalized_target.starts_with(&root_resolved) {
        return Err(ArchiveError(format!(
            "archive path escapes destination: {}",
            member_name
        )));
    }

    Ok(target)
}

fn normalize_path_simple(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for comp in path.components() {
        match comp {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            _ => out.push(comp),
        }
    }
    out
}

fn extract_zip(archive_path: &Path, destination: &Path) -> Result<(), ArchiveError> {
    let file = File::open(archive_path)
        .map_err(|e| ArchiveError(format!("could not open zip archive: {}", e)))?;
    let mut archive =
        ZipArchive::new(file).map_err(|e| ArchiveError(format!("invalid zip archive: {}", e)))?;

    for i in 0..archive.len() {
        let mut file = archive
            .by_index(i)
            .map_err(|e| ArchiveError(format!("zip read error: {}", e)))?;
        let name = file.name().to_string();

        if let Some(mode) = file.unix_mode() {
            // Check for symlinks in zip (mode & 0o170000 == 0o120000)
            if mode & 0o170000 == 0o120000 {
                return Err(ArchiveError(
                    "symbolic links are not allowed in ZIP archives".to_string(),
                ));
            }
        }

        let target = safe_member_path(destination, &name)?;
        if file.is_dir() {
            fs::create_dir_all(&target)
                .map_err(|e| ArchiveError(format!("could not create directory: {}", e)))?;
        } else {
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent)
                    .map_err(|e| ArchiveError(format!("could not create directory: {}", e)))?;
            }
            let mut outfile = File::create(&target)
                .map_err(|e| ArchiveError(format!("could not create file: {}", e)))?;
            io::copy(&mut file, &mut outfile)
                .map_err(|e| ArchiveError(format!("could not write file: {}", e)))?;

            #[cfg(unix)]
            if let Some(mode) = file.unix_mode() {
                use std::os::unix::fs::PermissionsExt;
                let _ = fs::set_permissions(&target, fs::Permissions::from_mode(mode));
            }
        }
    }

    Ok(())
}

fn extract_tar<R: Read>(
    mut archive: TarArchive<R>,
    destination: &Path,
) -> Result<(), ArchiveError> {
    let entries = archive
        .entries()
        .map_err(|e| ArchiveError(format!("tar read error: {}", e)))?;

    let dest_resolved = destination
        .canonicalize()
        .unwrap_or_else(|_| normalize_path_simple(destination));

    for entry_result in entries {
        let mut entry =
            entry_result.map_err(|e| ArchiveError(format!("tar entry read error: {}", e)))?;
        let path_bytes = entry.path_bytes();
        let name = String::from_utf8_lossy(&path_bytes).to_string();

        let target = safe_member_path(destination, &name)?;
        let entry_type = entry.header().entry_type();

        match entry_type {
            EntryType::Block | EntryType::Char | EntryType::Fifo => {
                return Err(ArchiveError(format!(
                    "archive contains a special device: {}",
                    name
                )));
            }
            EntryType::Symlink => {
                if let Some(link_name) = entry
                    .link_name()
                    .map_err(|e| ArchiveError(format!("tar link read error: {}", e)))?
                {
                    let link_target = if link_name.is_absolute() {
                        return Err(ArchiveError(format!(
                            "archive link escapes destination: {}",
                            name
                        )));
                    } else {
                        let parent = target.parent().unwrap_or(destination);
                        normalize_path_simple(&parent.join(&link_name))
                    };

                    if !link_target.starts_with(&dest_resolved) {
                        return Err(ArchiveError(format!(
                            "archive link escapes destination: {}",
                            name
                        )));
                    }
                }
            }
            EntryType::Link => {
                if let Some(link_name) = entry
                    .link_name()
                    .map_err(|e| ArchiveError(format!("tar link read error: {}", e)))?
                {
                    let link_str = link_name.to_string_lossy();
                    safe_member_path(destination, &link_str)?;
                }
            }
            _ => {}
        }

        entry
            .unpack_in(destination)
            .map_err(|e| ArchiveError(format!("failed to extract {}: {}", name, e)))?;
    }

    Ok(())
}

pub fn extract_archive(
    archive: &Path,
    destination: &Path,
    archive_type: &str,
) -> Result<(), ArchiveError> {
    fs::create_dir_all(destination)
        .map_err(|e| ArchiveError(format!("could not create destination: {}", e)))?;

    match archive_type {
        "zip" => extract_zip(archive, destination),
        "tgz" | "tar.gz" => {
            let file = File::open(archive)
                .map_err(|e| ArchiveError(format!("could not open archive: {}", e)))?;
            let decoder = GzDecoder::new(file);
            let tar_archive = TarArchive::new(decoder);
            extract_tar(tar_archive, destination)
        }
        "tar.zst" | "zst" => {
            let file = File::open(archive)
                .map_err(|e| ArchiveError(format!("could not open archive: {}", e)))?;
            let decoder = zstd::Decoder::new(file)
                .map_err(|e| ArchiveError(format!("zstd decompressor error: {}", e)))?;
            let tar_archive = TarArchive::new(decoder);
            extract_tar(tar_archive, destination)
        }
        _ => Err(ArchiveError(format!(
            "unsupported archive type: {}",
            archive_type
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_safe_member_path_traversal() {
        let root = Path::new("/tmp/test_dir");
        assert!(safe_member_path(root, "../outside").is_err());
        assert!(safe_member_path(root, "foo/../../outside").is_err());
        assert!(safe_member_path(root, "/absolute/path").is_err());
        assert!(safe_member_path(root, "C:\\windows\\system32").is_err());
        assert!(safe_member_path(root, "valid/path/file.txt").is_ok());
    }

    #[test]
    fn test_zip_extraction() {
        let dir = tempdir().unwrap();
        let zip_path = dir.path().join("test.zip");
        let dest = dir.path().join("extracted");

        {
            let file = File::create(&zip_path).unwrap();
            let mut zip = zip::ZipWriter::new(file);
            let options = zip::write::SimpleFileOptions::default();
            zip.start_file("hello.txt", options).unwrap();
            use std::io::Write;
            zip.write_all(b"Hello Rust!").unwrap();
            zip.finish().unwrap();
        }

        extract_archive(&zip_path, &dest, "zip").unwrap();
        let content = fs::read_to_string(dest.join("hello.txt")).unwrap();
        assert_eq!(content, "Hello Rust!");
    }
}
