//! Application state machine for the launcher.

use crate::agent::AgentSession;
use crate::config::{Profile, ProfileStore, Variant};
use crate::models::{native_api_base, InstalledModel, ModelEvent, ModelTask};
use ratatui::crossterm::event::{KeyCode, KeyModifiers};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq)]
pub enum Screen {
    MainMenu,
    Configure,
    Models,
    Profiles,
    Session,
}

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
    pub label: &'static str,
    pub value: String,
    pub kind: FieldKind,
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
        Self { label, value: format!("{v:.2}"), kind: FieldKind::Float, editing: false }
    }
    fn bool(label: &'static str, v: bool) -> Self {
        Self { label, value: if v { "on" } else { "off" }.into(), kind: FieldKind::Bool, editing: false }
    }
    fn select(label: &'static str, v: &str, opts: Vec<&'static str>) -> Self {
        Self { label, value: v.into(), kind: FieldKind::Select(opts), editing: false }
    }
}

pub const MENU_LOCAL: usize = 0;
pub const MENU_HYBRID: usize = 1;
pub const MENU_MODELS: usize = 2;
pub const MENU_PROFILES: usize = 3;
pub const MENU_QUIT: usize = 4;
pub const MENU_LEN: usize = 5;

const MAX_MODEL_LOGS: usize = 24;

pub struct App {
    pub screen: Screen,
    pub store: ProfileStore,
    pub profile: Profile,
    pub menu_idx: usize,
    pub profile_idx: usize,
    pub field_idx: usize,
    pub fields: Vec<Field>,
    pub status: Option<(String, bool)>,
    pub should_quit: bool,
    pub repo_root: PathBuf,
    pub session: Option<AgentSession>,
    pub last_session_lines: Vec<String>,
    pub input_buffer: String,
    pub input_editing: bool,
    pub session_scroll: u16,
    pub models: Vec<InstalledModel>,
    pub model_idx: usize,
    pub model_logs: Vec<String>,
    pub model_input_buffer: String,
    pub model_input_editing: bool,
    pub model_task_running: bool,
    model_task: Option<ModelTask>,
    pending_model_refresh: bool,
}

impl App {
    pub fn new(repo_root: PathBuf) -> Self {
        let store = ProfileStore::load();
        let profile = store.profiles.first().cloned().unwrap_or_default();
        let mut app = Self {
            screen: Screen::MainMenu,
            store,
            profile,
            menu_idx: 0,
            profile_idx: 0,
            field_idx: 0,
            fields: vec![],
            status: None,
            should_quit: false,
            repo_root,
            session: None,
            last_session_lines: vec![],
            input_buffer: String::new(),
            input_editing: false,
            session_scroll: 0,
            models: vec![],
            model_idx: 0,
            model_logs: vec![],
            model_input_buffer: String::new(),
            model_input_editing: false,
            model_task_running: false,
            model_task: None,
            pending_model_refresh: false,
        };
        app.rebuild_fields();
        app
    }

    pub fn rebuild_fields(&mut self) {
        let p = &self.profile;
        let mut f = vec![
            Field::text("Perfil", &p.name),
            Field::text("Modelo", &p.model),
            Field::path("Directorio", &p.work_dir),
            Field::text("Tag", &p.tag),
            Field::int("Contexto", p.ctx),
            Field::float("Temperatura", p.temperature),
            Field::path("Prompt sistema", &p.system_prompt),
        ];
        match p.variant {
            Variant::Local => {
                f.push(Field::text("API base", &p.api_base));
            }
            Variant::Hybrid => {
                f.push(Field::text("URL local", &p.local_url));
                f.push(Field::select("Backend", &p.backend, vec!["auto", "local", "groq"]));
                f.push(Field::bool("Critic mode", p.critic));
                f.push(Field::text("Modelo Groq", &p.groq_model));
                f.push(Field::select("Sandbox", profile_select_value(&p.sandbox), vec!["off", "docker"]));
                f.push(Field::text("Sandbox image", &p.sandbox_image));
            }
        }
        self.fields = f;
        self.field_idx = self.field_idx.min(self.fields.len().saturating_sub(1));
    }

    pub fn sync_profile(&mut self) {
        for f in &self.fields {
            match f.label {
                "Perfil" => self.profile.name = f.value.clone(),
                "Modelo" => self.profile.model = f.value.clone(),
                "Directorio" => self.profile.work_dir = f.value.clone(),
                "Tag" => self.profile.tag = f.value.clone(),
                "Contexto" => self.profile.ctx = f.value.parse().unwrap_or(self.profile.ctx),
                "Temperatura" => {
                    self.profile.temperature = f.value.parse().unwrap_or(self.profile.temperature)
                }
                "Prompt sistema" => self.profile.system_prompt = f.value.clone(),
                "API base" => self.profile.api_base = f.value.clone(),
                "URL local" => self.profile.local_url = f.value.clone(),
                "Backend" => self.profile.backend = f.value.clone(),
                "Critic mode" => self.profile.critic = f.value == "on",
                "Modelo Groq" => self.profile.groq_model = f.value.clone(),
                "Sandbox" => {
                    self.profile.sandbox = if f.value == "off" { String::new() } else { f.value.clone() }
                }
                "Sandbox image" => self.profile.sandbox_image = f.value.clone(),
                _ => {}
            }
        }
    }

    pub fn save_profile(&mut self) {
        self.sync_profile();
        self.store.upsert(self.profile.clone());
        match self.store.save() {
            Ok(()) => self.set_status(format!("Perfil '{}' guardado.", self.profile.name), false),
            Err(e) => self.set_status(format!("Error al guardar: {e}"), true),
        }
    }

    pub fn launch_session(&mut self) {
        self.sync_profile();
        if self.profile.model.trim().is_empty() {
            self.set_status("El modelo no puede estar vacio.".into(), true);
            return;
        }
        match AgentSession::spawn(&self.profile, &self.repo_root) {
            Ok(mut session) => {
                session
                    .lines
                    .push_back(format!("[launcher] Sesion iniciada: {} · {}", self.profile.variant.label(), self.profile.model));
                self.last_session_lines.clear();
                self.session = Some(session);
                self.screen = Screen::Session;
                self.input_buffer.clear();
                self.input_editing = false;
                self.session_scroll = 0;
                self.set_status("Agente en ejecucion.".into(), false);
            }
            Err(err) => self.set_status(format!("No se pudo lanzar el agente: {err}"), true),
        }
    }

    pub fn poll_session(&mut self) {
        let mut finished_lines: Option<Vec<String>> = None;
        let mut status_update: Option<(String, bool)> = None;

        if let Some(session) = self.session.as_mut() {
            if let Some(exit) = session.drain_events() {
                match exit {
                    Ok(status) if status.success() => {
                        session.lines.push_back("[launcher] Proceso finalizado correctamente.".into());
                        status_update = Some(("La sesion termino correctamente.".into(), false));
                    }
                    Ok(status) => {
                        session.lines.push_back(format!("[launcher] Proceso finalizado con codigo: {status}"));
                        status_update = Some(("La sesion termino con error.".into(), true));
                    }
                    Err(err) => {
                        session.lines.push_back(format!("[launcher] Error al esperar el proceso: {err}"));
                        status_update = Some(("Fallo al gestionar el proceso del agente.".into(), true));
                    }
                }
                finished_lines = Some(session.lines.iter().cloned().collect());
            }
        }

        if let Some(lines) = finished_lines {
            self.last_session_lines = lines;
            self.session = None;
        }
        if let Some((msg, is_err)) = status_update {
            self.set_status(msg, is_err);
        }
    }

    pub fn poll_models(&mut self) {
        while let Some(event) = self.model_task.as_ref().and_then(|task| task.try_recv()) {
            match event {
                ModelEvent::Status(msg) => {
                    self.push_model_log(msg.clone());
                    self.set_status(msg, false);
                }
                ModelEvent::Listed(result) => {
                    self.model_task = None;
                    self.model_task_running = false;
                    match result {
                        Ok(models) => {
                            let names: Vec<String> = models.iter().map(|model| model.name.clone()).collect();
                            self.models = models;
                            self.model_idx = names
                                .iter()
                                .position(|name| name == &self.profile.model)
                                .unwrap_or(0)
                                .min(self.models.len().saturating_sub(1));
                            self.push_model_log(format!("Modelos disponibles: {}", self.models.len()));
                            self.set_status("Listado de modelos actualizado.".into(), false);
                        }
                        Err(err) => {
                            self.push_model_log(err.clone());
                            self.set_status(err, true);
                        }
                    }
                }
                ModelEvent::Finished(result) => {
                    self.model_task = None;
                    self.model_task_running = false;
                    match result {
                        Ok(msg) => {
                            self.push_model_log(msg.clone());
                            self.set_status(msg, false);
                            if self.pending_model_refresh {
                                self.pending_model_refresh = false;
                                self.refresh_models();
                            }
                        }
                        Err(err) => {
                            self.pending_model_refresh = false;
                            self.push_model_log(err.clone());
                            self.set_status(err, true);
                        }
                    }
                }
            }
        }
    }

    pub fn stop_session(&mut self) {
        if let Some(session) = self.session.as_mut() {
            match session.stop() {
                Ok(()) => self.set_status("Senal de parada enviada al agente.".into(), false),
                Err(err) => self.set_status(format!("No se pudo detener el agente: {err}"), true),
            }
        }
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

    pub fn set_status(&mut self, msg: String, is_err: bool) {
        self.status = Some((msg, is_err));
    }

    pub fn session_log_lines(&self) -> Vec<String> {
        if let Some(session) = self.session.as_ref() {
            session.lines.iter().cloned().collect()
        } else {
            self.last_session_lines.clone()
        }
    }

    pub fn resolve_work_dir(&self) -> String {
        resolve_path_for_display(&self.profile.work_dir, &self.repo_root)
    }

    pub fn local_models_endpoint(&self) -> Result<String, String> {
        native_api_base(self.profile.local_management_base())
    }

    pub fn selected_model(&self) -> Option<&InstalledModel> {
        self.models.get(self.model_idx)
    }

    pub fn handle_key(&mut self, code: KeyCode, mods: KeyModifiers) {
        self.status = None;
        match self.screen.clone() {
            Screen::MainMenu => self.on_main_menu(code),
            Screen::Configure => self.on_configure(code, mods),
            Screen::Models => self.on_models(code),
            Screen::Profiles => self.on_profiles(code),
            Screen::Session => self.on_session(code, mods),
        }
    }

    fn on_main_menu(&mut self, code: KeyCode) {
        match code {
            KeyCode::Up | KeyCode::Char('k') => self.menu_idx = self.menu_idx.saturating_sub(1),
            KeyCode::Down | KeyCode::Char('j') => {
                if self.menu_idx + 1 < MENU_LEN {
                    self.menu_idx += 1;
                }
            }
            KeyCode::Enter => match self.menu_idx {
                MENU_LOCAL => self.go_configure(Variant::Local),
                MENU_HYBRID => self.go_configure(Variant::Hybrid),
                MENU_MODELS => self.open_models_screen(),
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

    fn go_configure(&mut self, variant: Variant) {
        self.profile.variant = variant.clone();
        if variant == Variant::Local && self.profile.tag == "HYBRID" {
            self.profile.tag = "AGENTE".into();
        }
        if variant == Variant::Hybrid && self.profile.tag == "AGENTE" {
            self.profile.tag = "HYBRID".into();
        }
        self.rebuild_fields();
        self.field_idx = 0;
        self.screen = Screen::Configure;
    }

    fn on_configure(&mut self, code: KeyCode, mods: KeyModifiers) {
        let editing = self.fields.get(self.field_idx).map(|f| f.editing).unwrap_or(false);
        if editing {
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
                        FieldKind::Float => c.is_ascii_digit() || c == '.',
                        _ => true,
                    };
                    if allowed {
                        f.value.push(c);
                    }
                }
            }
            _ => {}
        }
    }

    fn on_configure_nav(&mut self, code: KeyCode, mods: KeyModifiers) {
        let n = self.fields.len();
        match code {
            KeyCode::Tab | KeyCode::Down => self.field_idx = (self.field_idx + 1).min(n.saturating_sub(1)),
            KeyCode::BackTab | KeyCode::Up => self.field_idx = self.field_idx.saturating_sub(1),
            KeyCode::Enter | KeyCode::Char(' ') => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    match f.kind.clone() {
                        FieldKind::Bool => f.value = if f.value == "on" { "off".into() } else { "on".into() },
                        FieldKind::Select(opts) => {
                            let current = opts.iter().position(|&o| o == f.value).unwrap_or(0);
                            f.value = opts[(current + 1) % opts.len()].to_string();
                        }
                        _ => f.editing = true,
                    }
                }
            }
            KeyCode::F(5) => self.launch_session(),
            KeyCode::F(3) => self.open_models_screen(),
            KeyCode::Char('l') if mods.contains(KeyModifiers::CONTROL) => self.launch_session(),
            KeyCode::F(2) => self.save_profile(),
            KeyCode::Char('s') if mods.contains(KeyModifiers::CONTROL) => self.save_profile(),
            KeyCode::Esc => self.screen = Screen::MainMenu,
            _ => {}
        }
    }

    fn on_profiles(&mut self, code: KeyCode) {
        let n = self.store.profiles.len();
        match code {
            KeyCode::Up | KeyCode::Char('k') => self.profile_idx = self.profile_idx.saturating_sub(1),
            KeyCode::Down | KeyCode::Char('j') => {
                if n > 0 && self.profile_idx + 1 < n {
                    self.profile_idx += 1;
                }
            }
            KeyCode::Enter => self.load_selected_profile(),
            KeyCode::Char('d') => self.delete_selected_profile(),
            KeyCode::Esc => self.screen = Screen::MainMenu,
            _ => {}
        }
    }

    fn on_models(&mut self, code: KeyCode) {
        if self.model_input_editing {
            self.on_models_editing(code);
            return;
        }

        match code {
            KeyCode::Up | KeyCode::Char('k') => self.model_idx = self.model_idx.saturating_sub(1),
            KeyCode::Down | KeyCode::Char('j') => {
                if self.model_idx + 1 < self.models.len() {
                    self.model_idx += 1;
                }
            }
            KeyCode::Enter => self.use_selected_model(),
            KeyCode::Char('r') => self.refresh_models(),
            KeyCode::Char('p') => {
                self.model_input_editing = true;
                if self.model_input_buffer.trim().is_empty() {
                    self.model_input_buffer = self.profile.model.clone();
                }
            }
            KeyCode::Char('d') => self.delete_model(),
            KeyCode::Esc => {
                self.model_input_editing = false;
                self.screen = Screen::Configure;
            }
            _ => {}
        }
    }

    fn on_models_editing(&mut self, code: KeyCode) {
        match code {
            KeyCode::Enter => self.pull_model(),
            KeyCode::Esc => self.model_input_editing = false,
            KeyCode::Backspace => {
                self.model_input_buffer.pop();
            }
            KeyCode::Char(c) => self.model_input_buffer.push(c),
            _ => {}
        }
    }

    fn on_session(&mut self, code: KeyCode, mods: KeyModifiers) {
        if self.input_editing {
            match code {
                KeyCode::Enter => {
                    let line = self.input_buffer.clone();
                    let send_result = if let Some(session) = self.session.as_mut() {
                        session.send_line(&line)
                    } else {
                        Err("No hay sesion activa.".into())
                    };
                    match send_result {
                        Ok(()) => {
                            if let Some(session) = self.session.as_mut() {
                                session.lines.push_back(format!("> {line}"));
                            }
                            self.input_buffer.clear();
                            self.input_editing = false;
                        }
                        Err(err) => self.set_status(format!("No se pudo enviar entrada: {err}"), true),
                    }
                }
                KeyCode::Esc => self.input_editing = false,
                KeyCode::Backspace => {
                    self.input_buffer.pop();
                }
                KeyCode::Char(c) => self.input_buffer.push(c),
                _ => {}
            }
            return;
        }

        match code {
            KeyCode::Char('i') => self.input_editing = true,
            KeyCode::Char('c') if mods.contains(KeyModifiers::CONTROL) => self.stop_session(),
            KeyCode::F(6) => self.stop_session(),
            KeyCode::Up | KeyCode::Char('k') => self.session_scroll = self.session_scroll.saturating_add(1),
            KeyCode::Down | KeyCode::Char('j') => self.session_scroll = self.session_scroll.saturating_sub(1),
            KeyCode::Esc => self.screen = Screen::Configure,
            _ => {}
        }
    }

    fn open_models_screen(&mut self) {
        self.sync_profile();
        self.screen = Screen::Models;
        self.model_input_editing = false;
        self.model_input_buffer.clear();
        self.refresh_models();
    }

    fn refresh_models(&mut self) {
        if self.model_task_running {
            self.set_status("Ya hay una operacion de modelos en curso.".into(), true);
            return;
        }
        match ModelTask::spawn_refresh(&self.profile) {
            Ok(task) => {
                self.model_task = Some(task);
                self.model_task_running = true;
                self.pending_model_refresh = false;
                self.push_model_log("Actualizando listado de modelos...".into());
            }
            Err(err) => {
                self.push_model_log(err.clone());
                self.set_status(err, true);
            }
        }
    }

    fn pull_model(&mut self) {
        if self.model_task_running {
            self.set_status("Ya hay una operacion de modelos en curso.".into(), true);
            return;
        }
        let requested = self.model_input_buffer.trim().to_string();
        if requested.is_empty() {
            self.set_status("Introduce un nombre de modelo para descargar.".into(), true);
            return;
        }
        match ModelTask::spawn_pull(&self.profile, requested.clone()) {
            Ok(task) => {
                self.model_task = Some(task);
                self.model_task_running = true;
                self.pending_model_refresh = true;
                self.model_input_editing = false;
                self.push_model_log(format!("Descargando '{requested}'..."));
            }
            Err(err) => {
                self.push_model_log(err.clone());
                self.set_status(err, true);
            }
        }
    }

    fn delete_model(&mut self) {
        if self.model_task_running {
            self.set_status("Ya hay una operacion de modelos en curso.".into(), true);
            return;
        }
        let Some(model) = self.selected_model().map(|model| model.name.clone()) else {
            self.set_status("No hay modelo seleccionado.".into(), true);
            return;
        };
        match ModelTask::spawn_delete(&self.profile, model.clone()) {
            Ok(task) => {
                self.model_task = Some(task);
                self.model_task_running = true;
                self.pending_model_refresh = true;
                self.push_model_log(format!("Borrando '{model}'..."));
            }
            Err(err) => {
                self.push_model_log(err.clone());
                self.set_status(err, true);
            }
        }
    }

    fn use_selected_model(&mut self) {
        let Some(model) = self.selected_model().map(|model| model.name.clone()) else {
            self.set_status("No hay modelo seleccionado.".into(), true);
            return;
        };
        self.profile.model = model.clone();
        self.rebuild_fields();
        self.set_status(format!("Modelo activo del perfil: {model}"), false);
    }

    fn push_model_log(&mut self, line: String) {
        if self.model_logs.len() >= MAX_MODEL_LOGS {
            self.model_logs.remove(0);
        }
        self.model_logs.push(line);
    }
}

fn profile_select_value(value: &str) -> &str {
    if value.trim().is_empty() {
        "off"
    } else {
        value
    }
}

fn resolve_path_for_display(path: &str, repo_root: &Path) -> String {
    let raw = PathBuf::from(path);
    let resolved = if raw.is_absolute() { raw } else { repo_root.join(raw) };
    resolved.to_string_lossy().to_string()
}
