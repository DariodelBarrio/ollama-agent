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

const MAX_LOG_LINES: usize = 400;

#[derive(Debug, Clone)]
pub enum SessionEvent {
    Output(String),
}

pub struct AgentSession {
    child: Child,
    stdin: Option<ChildStdin>,
    rx: Receiver<SessionEvent>,
    pub lines: VecDeque<String>,
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
        })
    }

    pub fn drain_events(&mut self) -> Option<Result<ExitStatus, String>> {
        while let Ok(event) = self.rx.try_recv() {
            let SessionEvent::Output(line) = event;
            self.push_line(line);
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

    fn push_line(&mut self, line: String) {
        if self.lines.len() >= MAX_LOG_LINES {
            self.lines.pop_front();
        }
        self.lines.push_back(line);
    }
}

fn spawn_reader<T>(stream: T, tx: Sender<SessionEvent>, is_stderr: bool)
where
    T: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(stream);
        for line in reader.lines() {
            match line {
                Ok(text) => {
                    let rendered = if is_stderr && !text.is_empty() {
                        format!("[stderr] {text}")
                    } else {
                        text
                    };
                    let _ = tx.send(SessionEvent::Output(rendered));
                }
                Err(err) => {
                    let _ = tx.send(SessionEvent::Output(format!("[launcher] Error leyendo salida: {err}")));
                    break;
                }
            }
        }
    });
}

/// Returns (executable, prefix_args) for the best available Python on this OS.
pub fn find_python() -> (String, Vec<String>) {
    if probe("py", &["-3", "-c", "pass"]) {
        return ("py".into(), vec!["-3".into()]);
    }
    if probe("python3", &["--version"]) {
        return ("python3".into(), vec![]);
    }
    ("python".into(), vec![])
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

    if !profile.system_prompt.trim().is_empty() {
        cmd.arg("--system-prompt").arg(&profile.system_prompt);
    }

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
