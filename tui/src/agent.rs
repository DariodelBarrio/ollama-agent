//! Python subprocess management.
//!
//! Builds the exact command that the launcher would otherwise put in a .bat file,
//! then runs it with inherited stdin/stdout/stderr so the Python agent's own TUI
//! (Rich) works exactly as if launched directly.

use crate::config::{Profile, Variant};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};

// ── Python finder ─────────────────────────────────────────────────────────────

/// Returns (executable, prefix_args) for the best available Python on this OS.
///
/// On Windows the Python Launcher (`py -3`) is preferred because it respects
/// the user's installed version and works even when `python` is not in PATH.
pub fn find_python() -> (String, Vec<String>) {
    // Windows Python Launcher
    if probe("py", &["-3", "-c", "pass"]) {
        return ("py".into(), vec!["-3".into()]);
    }
    // Unix-style python3
    if probe("python3", &["--version"]) {
        return ("python3".into(), vec![]);
    }
    // Generic fallback
    ("python".into(), vec![])
}

fn probe(exe: &str, args: &[&str]) -> bool {
    Command::new(exe)
        .args(args)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

// ── Command builder ───────────────────────────────────────────────────────────

/// Build the subprocess command from a profile.
/// Does NOT spawn — callers decide stdin/stdout handling.
pub fn build_command(profile: &Profile, repo_root: &Path) -> Command {
    let script: PathBuf = match profile.variant {
        Variant::Local  => repo_root.join("src").join("agent.py"),
        Variant::Hybrid => repo_root.join("src").join("hybrid").join("agent.py"),
    };

    let (python, prefix) = find_python();
    let mut cmd = Command::new(&python);
    for a in &prefix {
        cmd.arg(a);
    }
    cmd.arg(&script);
    cmd.arg("--model").arg(&profile.model);
    cmd.arg("--dir").arg(&profile.work_dir);
    cmd.arg("--ctx").arg(profile.ctx.to_string());
    cmd.arg("--temp").arg(format!("{:.2}", profile.temperature));

    match profile.variant {
        Variant::Local => {
            cmd.arg("--api-base").arg(&profile.api_base);
        }
        Variant::Hybrid => {
            cmd.arg("--backend").arg(&profile.backend);
            cmd.arg("--local-url").arg(&profile.local_url);
            if !profile.groq_model.is_empty() {
                cmd.arg("--groq-model").arg(&profile.groq_model);
            }
            if profile.critic {
                cmd.arg("--critic");
            }
        }
    }

    cmd
}

// ── Launcher ──────────────────────────────────────────────────────────────────

/// Launch the agent, inheriting the terminal so Rich/prompt_toolkit work normally.
/// Blocks until the agent exits.
pub fn launch(profile: &Profile, repo_root: &Path) -> std::io::Result<ExitStatus> {
    build_command(profile, repo_root).status()
}

/// Return the command as a human-readable string (for the preview in the TUI).
pub fn command_preview(profile: &Profile, repo_root: &Path) -> String {
    let cmd = build_command(profile, repo_root);
    let prog = cmd.get_program().to_string_lossy().to_string();
    let args: Vec<String> = cmd
        .get_args()
        .map(|a| a.to_string_lossy().to_string())
        .collect();
    format!("{} {}", prog, args.join(" "))
}
