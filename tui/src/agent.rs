//! Python subprocess management for the TUI launcher.
//!
//! The TUI does not reimplement agent logic. It builds a Python command from a
//! saved profile, spawns the current agent as a child process, streams output,
//! and forwards plain line input from the launcher.

use crate::config::{Profile, Variant};
use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant};

const MAX_LOG_LINES: usize = 400;
const MAX_RECENT_TOOLS: usize = 8;
// Small batches cut redraw churn without turning the launcher into a delayed
// "buffered terminal". The window is short enough to keep output feeling live.
const OUTPUT_BATCH_LINES: usize = 8;
const OUTPUT_BATCH_WINDOW: Duration = Duration::from_millis(16);

#[derive(Debug, Clone)]
pub enum SessionEvent {
    OutputBatch(Vec<String>),
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RecentTool {
    pub title: String,
    pub target: String,
    pub result: String,
}

pub struct AgentSession {
    child: Child,
    stdin: Option<ChildStdin>,
    rx: Receiver<SessionEvent>,
    pub lines: VecDeque<String>,
    pub recent_tools: VecDeque<RecentTool>,
    changed_since_poll: bool,
}

impl AgentSession {
    pub fn spawn(profile: &Profile, repo_root: &Path) -> Result<Self, String> {
        let mut cmd = build_command(profile, repo_root);
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| e.to_string())?;
        let stdin = child.stdin.take();
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "No se pudo capturar stdout".to_string())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "No se pudo capturar stderr".to_string())?;

        let (tx, rx) = mpsc::channel();

        spawn_reader(stdout, tx.clone(), false);
        spawn_reader(stderr, tx.clone(), true);
        Ok(Self {
            child,
            stdin,
            rx,
            lines: VecDeque::new(),
            recent_tools: VecDeque::new(),
            changed_since_poll: false,
        })
    }

    pub fn drain_events(&mut self) -> Option<Result<ExitStatus, String>> {
        // The UI loop only needs to know whether something changed since the
        // last poll; it doesn't need per-line invalidation state.
        self.changed_since_poll = false;
        while let Ok(event) = self.rx.try_recv() {
            let SessionEvent::OutputBatch(lines) = event;
            self.push_lines(lines);
        }
        match self.child.try_wait() {
            Ok(Some(status)) => Some(Ok(status)),
            Ok(None) => None,
            Err(err) => Some(Err(err.to_string())),
        }
    }

    pub fn send_line(&mut self, line: &str) -> Result<(), String> {
        let stdin = self
            .stdin
            .as_mut()
            .ok_or_else(|| "La sesión no acepta más entrada".to_string())?;
        stdin
            .write_all(line.as_bytes())
            .map_err(|e| e.to_string())?;
        stdin.write_all(b"\n").map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())
    }

    pub fn stop(&mut self) -> Result<(), String> {
        self.child.kill().map_err(|e| e.to_string())
    }

    fn push_lines(&mut self, lines: Vec<String>) {
        if lines.is_empty() {
            return;
        }
        self.changed_since_poll = true;
        for line in lines {
            if line.starts_with("[tool] ")
                || line.starts_with("[tool-result] ")
                || line.starts_with("[role] ")
                || line.starts_with("[role-result] ")
            {
                if let Some(tool) = parse_recent_line(&line, self.recent_tools.back_mut()) {
                    if self.recent_tools.len() >= MAX_RECENT_TOOLS {
                        self.recent_tools.pop_front();
                    }
                    self.recent_tools.push_back(tool);
                }
                continue;
            }
            if self.lines.len() >= MAX_LOG_LINES {
                self.lines.pop_front();
            }
            self.lines.push_back(line);
        }
    }

    pub fn last_event_changed(&self) -> bool {
        self.changed_since_poll
    }
}

fn parse_recent_line(line: &str, pending: Option<&mut RecentTool>) -> Option<RecentTool> {
    if let Some(rest) = line.strip_prefix("[tool] ") {
        let mut parts = rest.splitn(2, " | ");
        let title = parts.next().unwrap_or("").trim().to_string();
        let target = parts.next().unwrap_or("").trim().to_string();
        return Some(RecentTool {
            title,
            target,
            result: "running".into(),
        });
    }
    if let Some(rest) = line.strip_prefix("[tool-result] ") {
        let mut parts = rest.splitn(2, " | ");
        let status = parts.next().unwrap_or("").trim();
        let summary = parts.next().unwrap_or("").trim().to_string();
        if let Some(tool) = pending {
            tool.result = if summary.is_empty() {
                status.into()
            } else {
                format!("{status}: {summary}")
            };
            return None;
        }
        return Some(RecentTool {
            title: "result".into(),
            target: String::new(),
            result: if summary.is_empty() {
                status.into()
            } else {
                format!("{status}: {summary}")
            },
        });
    }
    if let Some(rest) = line.strip_prefix("[role] ") {
        let mut parts = rest.splitn(2, " | ");
        let title = parts.next().unwrap_or("").trim().to_uppercase();
        let target = parts.next().unwrap_or("").trim().to_string();
        return Some(RecentTool {
            title,
            target,
            result: "running".into(),
        });
    }
    if let Some(rest) = line.strip_prefix("[role-result] ") {
        let mut parts = rest.splitn(2, " | ");
        let status = parts.next().unwrap_or("").trim().to_string();
        let summary = parts.next().unwrap_or("").trim().to_string();
        if let Some(tool) = pending {
            tool.result = if summary.is_empty() {
                status.clone()
            } else {
                format!("{status}: {summary}")
            };
            return None;
        }
        return Some(RecentTool {
            title: "ROLE".into(),
            target: String::new(),
            result: if summary.is_empty() {
                status
            } else {
                format!("{status}: {summary}")
            },
        });
    }
    None
}

fn spawn_reader<T>(stream: T, tx: Sender<SessionEvent>, is_stderr: bool)
where
    T: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(stream);
        // Batch stdout/stderr lines briefly so a fast model or chatty command
        // doesn't force one UI refresh per line.
        let mut batch = Vec::with_capacity(OUTPUT_BATCH_LINES);
        let mut last_flush = Instant::now() - OUTPUT_BATCH_WINDOW;
        for line in reader.lines() {
            match line {
                Ok(text) => {
                    let rendered = if is_stderr && !text.is_empty() {
                        format!("[stderr] {text}")
                    } else {
                        text
                    };
                    batch.push(rendered);
                    if batch.len() >= OUTPUT_BATCH_LINES
                        || last_flush.elapsed() >= OUTPUT_BATCH_WINDOW
                    {
                        flush_batch(&tx, &mut batch);
                        last_flush = Instant::now();
                    }
                }
                Err(err) => {
                    batch.push(format!("[launcher] Error leyendo salida: {err}"));
                    flush_batch(&tx, &mut batch);
                    break;
                }
            }
        }
        flush_batch(&tx, &mut batch);
    });
}

fn flush_batch(tx: &Sender<SessionEvent>, batch: &mut Vec<String>) {
    if batch.is_empty() {
        return;
    }
    let lines = std::mem::take(batch);
    let _ = tx.send(SessionEvent::OutputBatch(lines));
}

/// Returns (executable, prefix_args) for the best available Python on this OS.
pub fn find_python() -> (String, Vec<String>) {
    if let Ok(explicit) = std::env::var("OLLAMA_AGENT_PYTHON") {
        if !explicit.trim().is_empty() && probe_path(&explicit, &["-c", "pass"]) {
            return (explicit, vec![]);
        }
    }

    for path in python_path_candidates() {
        if probe_path(&path, &["-c", "pass"]) {
            return (path, vec![]);
        }
    }

    if probe("py", &["-3", "-c", "pass"]) {
        return ("py".into(), vec!["-3".into()]);
    }
    if probe("python3", &["--version"]) {
        return ("python3".into(), vec![]);
    }
    ("python".into(), vec![])
}

fn python_path_candidates() -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        out.push(
            cwd.join(".venv")
                .join("Scripts")
                .join("python.exe")
                .to_string_lossy()
                .to_string(),
        );
        out.push(
            cwd.join("venv")
                .join("Scripts")
                .join("python.exe")
                .to_string_lossy()
                .to_string(),
        );
    }
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let local = PathBuf::from(local);
        out.push(
            local
                .join("Python")
                .join("bin")
                .join("python.exe")
                .to_string_lossy()
                .to_string(),
        );
        for version in ["Python312", "Python311", "Python310", "Python39"] {
            out.push(
                local
                    .join("Programs")
                    .join("Python")
                    .join(version)
                    .join("python.exe")
                    .to_string_lossy()
                    .to_string(),
            );
        }
    }
    out
}

fn probe(exe: &str, args: &[&str]) -> bool {
    Command::new(exe)
        .args(args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn probe_path(exe: &str, args: &[&str]) -> bool {
    let path = Path::new(exe);
    path.exists()
        && Command::new(path)
            .args(args)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
}

pub fn build_command(profile: &Profile, repo_root: &Path) -> Command {
    let script: PathBuf = match profile.variant {
        Variant::Local => repo_root.join("src").join("agent.py"),
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
    cmd.arg("--tag").arg(&profile.tag);
    cmd.arg("--ctx").arg(profile.ctx.to_string());
    cmd.arg("--temp").arg(format!("{:.2}", profile.temperature));
    cmd.env("PYTHONUNBUFFERED", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");
    cmd.env("PYTHONUTF8", "1");

    if !profile.system_prompt.trim().is_empty() {
        cmd.arg("--system-prompt").arg(&profile.system_prompt);
    }

    match profile.variant {
        Variant::Local => {
            cmd.arg("--api-base").arg(&profile.api_base);
            if profile.read_only {
                cmd.arg("--read-only");
            }
            if profile.guided_mode {
                cmd.arg("--guided-mode");
            }
            cmd.env("OLLAMA_AGENT_SIMPLE_INPUT", "1");
        }
        Variant::Hybrid => {
            cmd.arg("--backend").arg(&profile.backend);
            cmd.arg("--local-url").arg(&profile.local_url);
            cmd.arg("--remote-provider").arg(&profile.cloud_provider);
            if !profile.remote_url.is_empty() {
                cmd.arg("--remote-url").arg(&profile.remote_url);
            }
            if !profile.remote_model.is_empty() {
                cmd.arg("--remote-model").arg(&profile.remote_model);
            }
            if !profile.groq_model.is_empty() {
                cmd.arg("--groq-model").arg(&profile.groq_model);
            }
            if profile.critic {
                cmd.arg("--critic");
            }
            if profile.read_only {
                cmd.arg("--read-only");
            }
            if profile.guided_mode {
                cmd.arg("--guided-mode");
            }
            if !profile.sandbox.trim().is_empty() {
                cmd.arg("--sandbox").arg(&profile.sandbox);
                cmd.arg("--sandbox-image").arg(&profile.sandbox_image);
            }
            if !profile.remote_api_key.trim().is_empty() {
                match profile.cloud_provider.as_str() {
                    "groq" => {
                        cmd.env("GROQ_API_KEY", &profile.remote_api_key);
                    }
                    _ => {
                        cmd.env("REMOTE_API_KEY", &profile.remote_api_key);
                    }
                };
            }
            cmd.env("OLLAMA_AGENT_SIMPLE_INPUT", "1");
        }
    }

    cmd.current_dir(repo_root);
    cmd
}

pub fn command_preview(profile: &Profile, repo_root: &Path) -> String {
    let cmd = build_command(profile, repo_root);
    let prog = cmd.get_program().to_string_lossy().to_string();
    let args: Vec<String> = cmd
        .get_args()
        .map(|a| a.to_string_lossy().to_string())
        .collect();
    format!("{} {}", prog, args.join(" "))
}

#[cfg(test)]
mod tests {
    use super::{parse_recent_line, RecentTool};

    #[test]
    fn tool_call_line_creates_recent_tool_entry() {
        let parsed = parse_recent_line("[tool] Read | README.md", None).unwrap();
        assert_eq!(parsed.title, "Read");
        assert_eq!(parsed.target, "README.md");
        assert_eq!(parsed.result, "running");
    }

    #[test]
    fn tool_result_updates_pending_entry() {
        let mut recent = RecentTool {
            title: "Read".into(),
            target: "README.md".into(),
            result: "running".into(),
        };
        let parsed =
            parse_recent_line("[tool-result] ok | 14 lines | README.md", Some(&mut recent));
        assert!(parsed.is_none());
        assert_eq!(recent.result, "ok: 14 lines | README.md");
    }

    #[test]
    fn role_line_creates_recent_action_entry() {
        let parsed = parse_recent_line("[role] planner | multi-file refactor", None).unwrap();
        assert_eq!(parsed.title, "PLANNER");
        assert_eq!(parsed.target, "multi-file refactor");
        assert_eq!(parsed.result, "running");
    }
}
