//! Interactive multiline prompt entry through the user's text editor.

use std::collections::HashMap;
use std::env;
use std::fmt;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::SystemTime;
use tempfile::NamedTempFile;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EditorError(pub String);

impl fmt::Display for EditorError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for EditorError {}

pub const PROMPT_MARKER: &str = "# --- Enter your prompt below this line ---\n";
pub const EDITOR_GUIDANCE: &str = "# Buddy multiline prompt editor\n\
# Write or paste your rough prompt below. Save and close the editor when done.\n\
# These guidance lines are not included in the prompt.\n\
# --- Enter your prompt below this line ---\n";

fn editor_candidates(environment: &HashMap<String, String>, platform_name: &str) -> Vec<String> {
    let mut candidates = Vec::new();
    for var in &["VISUAL", "EDITOR"] {
        if let Some(val) = environment.get(*var) {
            let trimmed = val.trim();
            if !trimmed.is_empty() && !candidates.contains(&trimmed.to_string()) {
                candidates.push(trimmed.to_string());
            }
        }
    }

    let fallbacks = if platform_name.starts_with("win") {
        vec!["notepad"]
    } else {
        vec!["vim", "vi"]
    };

    for fb in fallbacks {
        if !candidates.contains(&fb.to_string()) {
            candidates.push(fb.to_string());
        }
    }

    candidates
}

fn split_command_words(command_str: &str, is_windows: bool) -> Vec<String> {
    if is_windows {
        command_str
            .split_whitespace()
            .map(|s| s.trim_matches('"').to_string())
            .filter(|s| !s.is_empty())
            .collect()
    } else {
        let mut words = Vec::new();
        let mut current = String::new();
        let mut in_single = false;
        let mut in_double = false;
        let mut escaped = false;

        for c in command_str.chars() {
            if escaped {
                current.push(c);
                escaped = false;
            } else if c == '\\' && !in_single {
                escaped = true;
            } else if c == '\'' && !in_double {
                in_single = !in_single;
            } else if c == '"' && !in_single {
                in_double = !in_double;
            } else if c.is_whitespace() && !in_single && !in_double {
                if !current.is_empty() {
                    words.push(current);
                    current = String::new();
                }
            } else {
                current.push(c);
            }
        }
        if !current.is_empty() {
            words.push(current);
        }
        words
    }
}

fn find_executable_in_path(name: &str) -> Option<PathBuf> {
    if let Some(path_var) = env::var_os("PATH") {
        for path_dir in env::split_paths(&path_var) {
            let candidate = path_dir.join(name);
            if candidate.is_file() {
                return Some(candidate);
            }
            #[cfg(windows)]
            {
                let candidate_exe = path_dir.join(format!("{}.exe", name));
                if candidate_exe.is_file() {
                    return Some(candidate_exe);
                }
            }
        }
    }
    let direct = PathBuf::from(name);
    if direct.is_file() {
        Some(direct)
    } else {
        None
    }
}

pub fn resolve_editor(
    environment: &HashMap<String, String>,
    platform_name: &str,
) -> Result<Vec<String>, EditorError> {
    let mut attempted = Vec::new();
    let is_win = platform_name.starts_with("win");

    for candidate in editor_candidates(environment, platform_name) {
        let parts = split_command_words(&candidate, is_win);
        if parts.is_empty() {
            continue;
        }

        attempted.push(parts[0].clone());
        if let Some(exe) = find_executable_in_path(&parts[0]) {
            let mut resolved = vec![exe.to_string_lossy().to_string()];
            resolved.extend(parts[1..].iter().cloned());
            return Ok(resolved);
        }
    }

    let tried = if !attempted.is_empty() {
        attempted.join(", ")
    } else {
        "no editor commands".to_string()
    };

    Err(EditorError(format!(
        "no text editor is available (tried {}); set VISUAL or EDITOR to an installed editor",
        tried
    )))
}

pub fn extract_prompt(
    contents: &str,
    initial_contents: &str,
    was_saved: bool,
) -> Result<String, EditorError> {
    if contents == initial_contents && !was_saved {
        return Err(EditorError(
            "the editor closed without saving a prompt".to_string(),
        ));
    }

    let target_content = if contents.contains(PROMPT_MARKER) {
        contents.split(PROMPT_MARKER).nth(1).unwrap_or("")
    } else {
        contents
    };

    let prompt = target_content.trim();
    if prompt.is_empty() {
        return Err(EditorError("the editor saved an empty prompt".to_string()));
    }

    Ok(prompt.to_string())
}

pub fn read_prompt_from_editor() -> Result<String, EditorError> {
    let mut env_map = HashMap::new();
    for (k, v) in env::vars() {
        env_map.insert(k, v);
    }
    let platform = if cfg!(target_os = "windows") {
        "win32"
    } else if cfg!(target_os = "macos") {
        "darwin"
    } else {
        "linux"
    };

    let command_args = resolve_editor(&env_map, platform)?;

    let temp_file = NamedTempFile::new()
        .map_err(|e| EditorError(format!("could not create temporary file: {}", e)))?;
    let path = temp_file.path().to_path_buf();

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
    }

    fs::write(&path, EDITOR_GUIDANCE)
        .map_err(|e| EditorError(format!("could not write to temporary file: {}", e)))?;

    let initial_mtime = fs::metadata(&path)
        .and_then(|m| m.modified())
        .unwrap_or(SystemTime::UNIX_EPOCH);

    let status = Command::new(&command_args[0])
        .args(&command_args[1..])
        .arg(&path)
        .status()
        .map_err(|e| EditorError(format!("could not start the text editor: {}", e)))?;

    if !status.success() {
        return Err(EditorError(format!(
            "the text editor exited unsuccessfully (exit code {:?})",
            status.code()
        )));
    }

    let current_mtime = fs::metadata(&path)
        .and_then(|m| m.modified())
        .unwrap_or(SystemTime::UNIX_EPOCH);

    let was_saved = current_mtime != initial_mtime;

    let contents = fs::read_to_string(&path)
        .map_err(|e| EditorError(format!("could not read the prompt from the editor: {}", e)))?;

    extract_prompt(&contents, EDITOR_GUIDANCE, was_saved)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_prompt_normal() {
        let saved = format!("{}  Refactor this function cleanly.  \n", EDITOR_GUIDANCE);
        let extracted = extract_prompt(&saved, EDITOR_GUIDANCE, true).unwrap();
        assert_eq!(extracted, "Refactor this function cleanly.");
    }

    #[test]
    fn test_extract_prompt_not_saved() {
        assert!(extract_prompt(EDITOR_GUIDANCE, EDITOR_GUIDANCE, false).is_err());
    }

    #[test]
    fn test_extract_prompt_empty() {
        let saved = format!("{}   \n", EDITOR_GUIDANCE);
        assert!(extract_prompt(&saved, EDITOR_GUIDANCE, true).is_err());
    }
}
