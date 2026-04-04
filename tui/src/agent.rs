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
// Small batches cut redraw churn without turning the launcher into a delayed
// "buffered terminal". The window is short enough to keep output feeling live.
const OUTPUT_BATCH_LINES: usize = 8;
const OUTPUT_BATCH_WINDOW: Duration = Duration::from_millis(16);

#[derive(Debug, Clone)]
pub enum SessionEvent {
    OutputBatch(Vec<String>),
}

pub struct AgentSession {
    child: Child,
    stdin: Option<ChildStdin>,
    rx: Receiver<SessionEvent>,
    pub lines: VecDeque<String>,
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
        let stdout = child.stdout.take().ok_or_else(|| "No se pudo capturar stdout".to_string())?;
        let stderr = child.stderr.take().ok_or_else(|| "No se pudo capturar stderr".to_string())?;

        let (tx, rx) = mpsc::channel();

        spawn_reader(stdout, tx.clone(), false);
        spawn_reader(stderr, tx.clone(), true);
        Ok(Self {
            child,
            stdin,
            rx,
            lines: VecDeque::new(),
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
        let stdin = self.stdin.as_mut().ok_or_else(|| "La sesión no acepta más entrada".to_string())?;
        stdin.write_all(line.as_bytes()).map_err(|e| e.to_string())?;
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
                    if batch.len() >= OUTPUT_BATCH_LINES || last_flush.elapsed() >= OUTPUT_BATCH_WINDOW {
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
        out.push(cwd.join(".venv").join("Scripts").join("python.exe").to_string_lossy().to_string());
        out.push(cwd.join("venv").join("Scripts").join("python.exe").to_string_lossy().to_string());
    }
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let local = PathBuf::from(local);
        out.push(local.join("Python").join("bin").join("python.exe").to_string_lossy().to_string());
        for version in ["Python312", "Python311", "Python310", "Python39"] {
            out.push(local.join("Programs").join("Python").join(version).join("python.exe").to_string_lossy().to_string());
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
            cmd.env("OLLAMA_AGENT_SIMPLE_INPUT", "1");
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
            if !profile.sandbox.trim().is_empty() {
                cmd.arg("--sandbox").arg(&profile.sandbox);
                cmd.arg("--sandbox-image").arg(&profile.sandbox_image);
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
