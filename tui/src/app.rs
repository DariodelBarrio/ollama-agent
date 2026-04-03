//! Application state machine.
//!
//! Three screens:  MainMenu → Configure → (launch) → back to Configure
//!                 MainMenu → Profiles  → (load)   → Configure
//!
//! No business logic lives in ui.rs; everything that changes state is here.

use crate::config::{Profile, ProfileStore, Variant};
use ratatui::crossterm::event::{KeyCode, KeyModifiers};
use std::path::PathBuf;

// ── Screens ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub enum Screen {
    MainMenu,
    Configure,
    Profiles,
}

// ── Form fields ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub enum FieldKind {
    Text,
    Path,
    Integer,
    Float,
    Bool,
    Select(Vec<&'static str>),
}

#[derive(Debug, Clone)]
pub struct Field {
    pub label:   &'static str,
    pub value:   String,
    pub kind:    FieldKind,
    pub editing: bool,
}

impl Field {
    fn text(label: &'static str, v: &str) -> Self {
        Self { label, value: v.into(), kind: FieldKind::Text, editing: false }
    }
    fn path(label: &'static str, v: &str) -> Self {
        Self { label, value: v.into(), kind: FieldKind::Path, editing: false }
    }
    fn int(label: &'static str, v: u32) -> Self {
        Self { label, value: v.to_string(), kind: FieldKind::Integer, editing: false }
    }
    fn float(label: &'static str, v: f32) -> Self {
        Self { label, value: format!("{:.2}", v), kind: FieldKind::Float, editing: false }
    }
    fn bool(label: &'static str, v: bool) -> Self {
        Self { label, value: if v { "on" } else { "off" }.into(), kind: FieldKind::Bool, editing: false }
    }
    fn select(label: &'static str, v: &str, opts: Vec<&'static str>) -> Self {
        Self { label, value: v.into(), kind: FieldKind::Select(opts), editing: false }
    }
}

// ── Main menu items ───────────────────────────────────────────────────────────

pub const MENU_LOCAL:    usize = 0;
pub const MENU_HYBRID:   usize = 1;
pub const MENU_PROFILES: usize = 2;
pub const MENU_QUIT:     usize = 3;
pub const MENU_LEN:      usize = 4;

// ── App ───────────────────────────────────────────────────────────────────────

pub struct App {
    pub screen:       Screen,
    pub store:        ProfileStore,
    pub profile:      Profile,
    pub menu_idx:     usize,
    pub profile_idx:  usize,
    pub field_idx:    usize,
    pub fields:       Vec<Field>,
    /// (message, is_error)
    pub status:       Option<(String, bool)>,
    pub should_quit:  bool,
    /// Set to true by the event loop; main.rs acts on it and resets it.
    pub launch_pending: bool,
    pub repo_root:    PathBuf,
}

impl App {
    pub fn new(repo_root: PathBuf) -> Self {
        let store   = ProfileStore::load();
        let profile = store.profiles.first().cloned().unwrap_or_default();
        let mut app = Self {
            screen:        Screen::MainMenu,
            store,
            profile,
            menu_idx:      0,
            profile_idx:   0,
            field_idx:     0,
            fields:        vec![],
            status:        None,
            should_quit:   false,
            launch_pending: false,
            repo_root,
        };
        app.rebuild_fields();
        app
    }

    // ── Field management ──────────────────────────────────────────────────────

    pub fn rebuild_fields(&mut self) {
        let p = &self.profile;
        let mut f = vec![
            Field::text("Perfil",            &p.name),
            Field::text("Modelo",            &p.model),
            Field::path("Directorio",        &p.work_dir),
            Field::int( "Contexto (tokens)", p.ctx),
            Field::float("Temperatura",      p.temperature),
        ];
        match p.variant {
            Variant::Local => {
                f.push(Field::text("API base", &p.api_base));
            }
            Variant::Hybrid => {
                f.push(Field::text("URL local",  &p.local_url));
                f.push(Field::select("Backend", &p.backend, vec!["auto", "local", "groq"]));
                f.push(Field::bool("Critic mode", p.critic));
                f.push(Field::text("Modelo Groq", &p.groq_model));
            }
        }
        self.fields = f;
        self.field_idx = self.field_idx.min(self.fields.len().saturating_sub(1));
    }

    /// Sync the `profile` struct from the current field values.
    pub fn sync_profile(&mut self) {
        for f in &self.fields {
            match f.label {
                "Perfil"            => self.profile.name        = f.value.clone(),
                "Modelo"            => self.profile.model       = f.value.clone(),
                "Directorio"        => self.profile.work_dir    = f.value.clone(),
                "Contexto (tokens)" => self.profile.ctx         = f.value.parse().unwrap_or(self.profile.ctx),
                "Temperatura"       => self.profile.temperature = f.value.parse().unwrap_or(self.profile.temperature),
                "API base"          => self.profile.api_base    = f.value.clone(),
                "URL local"         => self.profile.local_url   = f.value.clone(),
                "Backend"           => self.profile.backend     = f.value.clone(),
                "Critic mode"       => self.profile.critic      = f.value == "on",
                "Modelo Groq"       => self.profile.groq_model  = f.value.clone(),
                _ => {}
            }
        }
    }

    // ── Actions ───────────────────────────────────────────────────────────────

    pub fn save_profile(&mut self) {
        self.sync_profile();
        self.store.upsert(self.profile.clone());
        match self.store.save() {
            Ok(())  => self.set_status(format!("Perfil '{}' guardado.", self.profile.name), false),
            Err(e)  => self.set_status(format!("Error al guardar: {e}"), true),
        }
    }

    pub fn go_configure(&mut self, variant: Variant) {
        self.profile.variant = variant;
        self.rebuild_fields();
        self.field_idx = 0;
        self.screen    = Screen::Configure;
        self.status    = None;
    }

    pub fn load_selected_profile(&mut self) {
        if let Some(p) = self.store.profiles.get(self.profile_idx).cloned() {
            let name = p.name.clone();
            self.profile = p;
            self.rebuild_fields();
            self.screen = Screen::Configure;
            self.set_status(format!("Perfil '{name}' cargado."), false);
        }
    }

    pub fn delete_selected_profile(&mut self) {
        if let Some(name) = self.store.profiles.get(self.profile_idx).map(|p| p.name.clone()) {
            self.store.remove(&name);
            let _ = self.store.save();
            self.profile_idx = self.profile_idx.saturating_sub(1);
            self.set_status(format!("Perfil '{name}' eliminado."), false);
        }
    }

    fn set_status(&mut self, msg: String, is_err: bool) {
        self.status = Some((msg, is_err));
    }

    // ── Input handling ────────────────────────────────────────────────────────

    pub fn handle_key(&mut self, code: KeyCode, mods: KeyModifiers) {
        // Clear transient status on any keypress
        self.status = None;

        match self.screen.clone() {
            Screen::MainMenu  => self.on_main_menu(code),
            Screen::Configure => self.on_configure(code, mods),
            Screen::Profiles  => self.on_profiles(code),
        }
    }

    fn on_main_menu(&mut self, code: KeyCode) {
        match code {
            KeyCode::Up   | KeyCode::Char('k') => {
                self.menu_idx = self.menu_idx.saturating_sub(1);
            }
            KeyCode::Down | KeyCode::Char('j') => {
                if self.menu_idx + 1 < MENU_LEN { self.menu_idx += 1; }
            }
            KeyCode::Enter => match self.menu_idx {
                MENU_LOCAL    => self.go_configure(Variant::Local),
                MENU_HYBRID   => self.go_configure(Variant::Hybrid),
                MENU_PROFILES => {
                    self.profile_idx = 0;
                    self.screen = Screen::Profiles;
                }
                MENU_QUIT | _ => self.should_quit = true,
            },
            KeyCode::Char('q') => self.should_quit = true,
            _ => {}
        }
    }

    fn on_configure(&mut self, code: KeyCode, mods: KeyModifiers) {
        let currently_editing = self.fields.get(self.field_idx).map_or(false, |f| f.editing);

        if currently_editing {
            self.on_configure_editing(code);
        } else {
            self.on_configure_nav(code, mods);
        }
    }

    fn on_configure_editing(&mut self, code: KeyCode) {
        match code {
            KeyCode::Enter | KeyCode::Esc => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    f.editing = false;
                }
            }
            KeyCode::Backspace => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    f.value.pop();
                }
            }
            KeyCode::Char(c) => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    let allowed = match f.kind {
                        FieldKind::Integer => c.is_ascii_digit(),
                        FieldKind::Float   => c.is_ascii_digit() || c == '.',
                        _                  => true,
                    };
                    if allowed { f.value.push(c); }
                }
            }
            _ => {}
        }
    }

    fn on_configure_nav(&mut self, code: KeyCode, mods: KeyModifiers) {
        let n = self.fields.len();
        match code {
            KeyCode::Tab | KeyCode::Down => {
                self.field_idx = (self.field_idx + 1).min(n.saturating_sub(1));
            }
            KeyCode::BackTab | KeyCode::Up => {
                self.field_idx = self.field_idx.saturating_sub(1);
            }
            KeyCode::Enter | KeyCode::Char(' ') => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    match f.kind.clone() {
                        FieldKind::Bool => {
                            f.value = if f.value == "on" { "off".into() } else { "on".into() };
                        }
                        FieldKind::Select(opts) => {
                            let cur  = opts.iter().position(|&o| o == f.value).unwrap_or(0);
                            let next = (cur + 1) % opts.len();
                            f.value  = opts[next].to_string();
                        }
                        _ => { f.editing = true; }
                    }
                }
            }
            // F5 → launch
            KeyCode::F(5) => {
                self.sync_profile();
                self.launch_pending = true;
            }
            // Ctrl+L → launch
            KeyCode::Char('l') if mods.contains(KeyModifiers::CONTROL) => {
                self.sync_profile();
                self.launch_pending = true;
            }
            // F2 → save
            KeyCode::F(2) => {
                self.save_profile();
            }
            // Ctrl+S → save
            KeyCode::Char('s') if mods.contains(KeyModifiers::CONTROL) => {
                self.save_profile();
            }
            KeyCode::Esc => {
                self.screen = Screen::MainMenu;
            }
            _ => {}
        }
    }

    fn on_profiles(&mut self, code: KeyCode) {
        let n = self.store.profiles.len();
        match code {
            KeyCode::Up   | KeyCode::Char('k') => {
                self.profile_idx = self.profile_idx.saturating_sub(1);
            }
            KeyCode::Down | KeyCode::Char('j') => {
                if n > 0 && self.profile_idx + 1 < n { self.profile_idx += 1; }
            }
            KeyCode::Enter               => self.load_selected_profile(),
            KeyCode::Char('d')           => self.delete_selected_profile(),
            KeyCode::Esc                 => self.screen = Screen::MainMenu,
            _ => {}
        }
    }
}
