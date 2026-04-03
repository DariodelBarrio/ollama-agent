//! Entry point: terminal setup, event loop, agent handoff.
//!
//! The TUI suspends itself before launching the Python agent so that Rich and
//! prompt_toolkit have a clean, normal terminal to work with. When the agent
//! exits, the TUI resumes from where it left off.

mod agent;
mod app;
mod config;
mod ui;

use std::{
    io::{self, BufRead, Write},
    path::PathBuf,
    time::Duration,
};

use app::App;
use ratatui::{
    Terminal,
    backend::CrosstermBackend,
    crossterm::{
        cursor,
        event::{self, Event, KeyEventKind},
        execute,
        terminal::{
            disable_raw_mode, enable_raw_mode,
            EnterAlternateScreen, LeaveAlternateScreen,
        },
    },
};

// ── Main ──────────────────────────────────────────────────────────────────────

fn main() {
    if let Err(e) = run() {
        // Ensure the terminal is restored even on unexpected errors.
        let _ = disable_raw_mode();
        let _ = execute!(io::stdout(), LeaveAlternateScreen, cursor::Show);
        eprintln!("Error: {e}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let repo_root = find_repo_root()?;

    // ── Terminal setup ────────────────────────────────────────────────────────
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, cursor::Hide)?;

    // Restore terminal on panic so the shell isn't left broken.
    std::panic::set_hook(Box::new(|info| {
        let _ = disable_raw_mode();
        let _ = execute!(io::stdout(), LeaveAlternateScreen, cursor::Show);
        eprintln!("\nPanic: {info}");
    }));

    let backend  = CrosstermBackend::new(io::stdout());
    let mut term = Terminal::new(backend)?;

    let mut app = App::new(repo_root.clone());

    // ── Event loop ────────────────────────────────────────────────────────────
    loop {
        term.draw(|f| ui::render(&app, f))?;

        if event::poll(Duration::from_millis(50))? {
            if let Event::Key(key) = event::read()? {
                // Filter out key-release events (Windows sends both press and release).
                if key.kind == KeyEventKind::Press {
                    app.handle_key(key.code, key.modifiers);
                }
            }
        }

        if app.should_quit {
            break;
        }

        if app.launch_pending {
            app.launch_pending = false;
            launch_agent_session(&mut term, &app)?;
        }
    }

    // ── Teardown ──────────────────────────────────────────────────────────────
    execute!(term.backend_mut(), LeaveAlternateScreen, cursor::Show)?;
    disable_raw_mode()?;
    Ok(())
}

// ── Agent handoff ─────────────────────────────────────────────────────────────

/// Suspend the TUI, run the Python agent in the normal terminal, then resume.
fn launch_agent_session(
    term: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &App,
) -> Result<(), Box<dyn std::error::Error>> {
    // 1. Give the terminal back to the shell.
    execute!(term.backend_mut(), LeaveAlternateScreen, cursor::Show)?;
    disable_raw_mode()?;

    // 2. Print a small separator so the user knows the agent is starting.
    println!();
    println!("─── ollama-agent  ({} · {}) ─────────────────────────────",
        app.profile.variant.label(), app.profile.model);
    println!();
    io::stdout().flush()?;

    // 3. Run the agent (inherits stdin/stdout/stderr).
    let status = agent::launch(&app.profile, &app.repo_root);

    // 4. Wait for acknowledgement before re-entering the TUI.
    println!();
    match &status {
        Ok(s) if s.success() => println!("[ agente finalizado correctamente ]"),
        Ok(s) => println!("[ agente finalizado — código de salida: {} ]", s),
        Err(e) => println!("[ error al lanzar el agente: {} ]", e),
    }
    print!("\nPresiona Enter para volver al launcher... ");
    io::stdout().flush()?;

    // Drain until newline (works whether stdin had pending chars or not).
    let stdin = io::stdin();
    let mut buf = String::new();
    stdin.lock().read_line(&mut buf)?;

    // 5. Restore TUI.
    enable_raw_mode()?;
    execute!(term.backend_mut(), EnterAlternateScreen, cursor::Hide)?;
    term.clear()?;

    Ok(())
}

// ── Repo root discovery ───────────────────────────────────────────────────────

/// Walk up the directory tree looking for src/agent.py.
///
/// Also honours the OLLAMA_AGENT_ROOT environment variable for cases where
/// the binary is installed outside the repo (e.g. ~/.local/bin/oat).
fn find_repo_root() -> Result<PathBuf, Box<dyn std::error::Error>> {
    if let Ok(val) = std::env::var("OLLAMA_AGENT_ROOT") {
        let p = PathBuf::from(&val);
        if p.join("src").join("agent.py").exists() {
            return Ok(p);
        }
        return Err(format!("OLLAMA_AGENT_ROOT={val} no contiene src/agent.py").into());
    }

    let mut dir = std::env::current_dir()?;
    loop {
        if dir.join("src").join("agent.py").exists() {
            return Ok(dir);
        }
        match dir.parent() {
            Some(p) => dir = p.to_path_buf(),
            None    => break,
        }
    }

    Err(concat!(
        "No se encontró el repo de ollama-agent.\n",
        "Ejecuta `oat` desde la raíz del repo o define la variable de entorno:\n",
        "  set OLLAMA_AGENT_ROOT=C:\\ruta\\al\\repo   (Windows)\n",
        "  export OLLAMA_AGENT_ROOT=/ruta/al/repo   (Linux/macOS)",
    ).into())
}
