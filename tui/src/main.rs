//! Entry point for the terminal launcher.

mod agent;
mod app;
mod config;
mod models;
mod preflight;
mod ui;

use std::{io, path::PathBuf};

use app::App;
use ratatui::{
    backend::CrosstermBackend,
    crossterm::{
        cursor,
        event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyEventKind},
        execute,
        terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
    },
    layout::Rect,
    Terminal,
};

fn main() {
    if let Err(err) = run() {
        let _ = disable_raw_mode();
        let _ = execute!(
            io::stdout(),
            LeaveAlternateScreen,
            DisableMouseCapture,
            cursor::Show
        );
        eprintln!("Error: {err}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let repo_root = find_repo_root()?;

    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, cursor::Hide)?;

    std::panic::set_hook(Box::new(|info| {
        let _ = disable_raw_mode();
        let _ = execute!(
            io::stdout(),
            LeaveAlternateScreen,
            DisableMouseCapture,
            cursor::Show
        );
        eprintln!("\nPanic: {info}");
    }));

    let backend = CrosstermBackend::new(io::stdout());
    let mut term = Terminal::new(backend)?;
    let mut app = App::new(repo_root);
    let mut mouse_capture_enabled = false;
    // Draw only when state changed. The app already polls background tasks
    // continuously, so unconditional redraws would just re-render the same
    // frame and make navigation feel heavier on Windows terminals.
    let mut dirty = true;

    loop {
        if app.poll_session() {
            dirty = true;
        }
        if app.poll_models() {
            dirty = true;
        }

        if dirty {
            term.draw(|f| ui::render(&app, f))?;
            dirty = false;
        }

        let wants_mouse_capture = app.wants_mouse_capture();
        if wants_mouse_capture != mouse_capture_enabled {
            if wants_mouse_capture {
                execute!(term.backend_mut(), EnableMouseCapture)?;
            } else {
                execute!(term.backend_mut(), DisableMouseCapture)?;
            }
            mouse_capture_enabled = wants_mouse_capture;
        }

        if event::poll(app.poll_timeout())? {
            match event::read()? {
                Event::Key(key) => {
                    if key.kind == KeyEventKind::Press {
                        app.handle_key(key.code, key.modifiers);
                        dirty = true;
                    }
                }
                Event::Mouse(mouse) => {
                    let size = term.size()?;
                    app.handle_mouse(mouse, Rect::new(0, 0, size.width, size.height));
                    dirty = true;
                }
                _ => {}
            }
        }

        if app.should_quit {
            break;
        }
    }

    execute!(
        term.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture,
        cursor::Show
    )?;
    disable_raw_mode()?;
    Ok(())
}

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
            Some(parent) => dir = parent.to_path_buf(),
            None => break,
        }
    }

    Err(concat!(
        "No se encontró el repo de ollama-agent.\n",
        "Ejecuta `oat` desde la raíz del repo o define OLLAMA_AGENT_ROOT."
    )
    .into())
}
