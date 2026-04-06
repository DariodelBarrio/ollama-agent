//! Application state machine for the launcher.

use crate::agent::{AgentSession, RecentTool};
use crate::config::{Profile, ProfileStore, Variant};
use crate::models::{native_api_base, InstalledModel, ModelEvent, ModelTask};
use crate::preflight::{self, PreflightReport};
use ratatui::{
    crossterm::event::{KeyCode, KeyModifiers, MouseButton, MouseEvent, MouseEventKind},
    layout::{Constraint, Layout, Rect},
};
use std::{
    collections::VecDeque,
    path::{Path, PathBuf},
    time::Duration,
};

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
        Self {
            label,
            value: v.into(),
            kind: FieldKind::Text,
            editing: false,
        }
    }
    fn path(label: &'static str, v: &str) -> Self {
        Self {
            label,
            value: v.into(),
            kind: FieldKind::Path,
            editing: false,
        }
    }
    fn int(label: &'static str, v: u32) -> Self {
        Self {
            label,
            value: v.to_string(),
            kind: FieldKind::Integer,
            editing: false,
        }
    }
    fn float(label: &'static str, v: f32) -> Self {
        Self {
            label,
            value: format!("{v:.2}"),
            kind: FieldKind::Float,
            editing: false,
        }
    }
    fn bool(label: &'static str, v: bool) -> Self {
        Self {
            label,
            value: if v { "on" } else { "off" }.into(),
            kind: FieldKind::Bool,
            editing: false,
        }
    }
    fn select(label: &'static str, v: &str, opts: Vec<&'static str>) -> Self {
        Self {
            label,
            value: v.into(),
            kind: FieldKind::Select(opts),
            editing: false,
        }
    }
}

pub const MENU_LOCAL: usize = 0;
pub const MENU_HYBRID: usize = 1;
pub const MENU_MODELS: usize = 2;
pub const MENU_PROFILES: usize = 3;
pub const MENU_QUIT: usize = 4;
pub const MENU_LEN: usize = 5;

const MAX_MODEL_LOGS: usize = 24;
const GPU_OPTIONS: [&str; 5] = ["custom", "5060", "5070", "5080", "5090"];
const GPU_PRESET_OPTIONS: [&str; 3] = ["safe", "balanced", "max"];
const CLOUD_PROVIDER_OPTIONS: [&str; 5] = ["none", "groq", "openai", "openrouter", "custom"];

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
    pub last_session_lines: VecDeque<String>,
    pub last_session_tools: VecDeque<RecentTool>,
    pub input_buffer: String,
    pub input_cursor: usize,
    pub session_scroll: u16,
    pub session_follow_output: bool,
    pub session_mouse_mode: bool,
    session_scroll_dragging: bool,
    session_scroll_drag_offset: u16,
    pub models: Vec<InstalledModel>,
    pub model_idx: usize,
    pub model_logs: Vec<String>,
    pub model_progress: Option<String>,
    pub model_input_buffer: String,
    pub model_input_editing: bool,
    pub model_task_running: bool,
    model_task: Option<ModelTask>,
    pending_model_refresh: bool,
    // These previews are derived from the editable field list. Caching them
    // avoids rebuilding the launch summary on every frame while navigating.
    pub configure_preview_command: String,
    pub configure_preview_detail: String,
    pub preflight_report: Option<PreflightReport>,
    // Session metadata is frozen at launch time so the session screen doesn't
    // rebuild command/path previews while only the live output is changing.
    pub session_command_preview: String,
    pub session_work_dir_preview: String,
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
            last_session_lines: VecDeque::new(),
            last_session_tools: VecDeque::new(),
            input_buffer: String::new(),
            input_cursor: 0,
            session_scroll: 0,
            session_follow_output: true,
            session_mouse_mode: false,
            session_scroll_dragging: false,
            session_scroll_drag_offset: 0,
            models: vec![],
            model_idx: 0,
            model_logs: vec![],
            model_progress: None,
            model_input_buffer: String::new(),
            model_input_editing: false,
            model_task_running: false,
            model_task: None,
            pending_model_refresh: false,
            configure_preview_command: String::new(),
            configure_preview_detail: String::new(),
            preflight_report: None,
            session_command_preview: String::new(),
            session_work_dir_preview: String::new(),
        };
        app.rebuild_fields();
        app
    }

    pub fn rebuild_fields(&mut self) {
        let p = &self.profile;
        let mut f = vec![
            Field::text("Perfil", &p.name),
            Field::select("GPU", &p.gpu_profile, GPU_OPTIONS.to_vec()),
            Field::select("GPU preset", &p.gpu_preset, GPU_PRESET_OPTIONS.to_vec()),
            Field::text("Modelo", &p.model),
            Field::path("Project Root", &p.work_dir),
            Field::text("Tag", &p.tag),
            Field::int("Contexto", p.ctx),
            Field::float("Temperatura", p.temperature),
            Field::path("Prompt sistema", &p.system_prompt),
            Field::bool("Read only", p.read_only),
            Field::bool("Guided mode", p.guided_mode),
        ];
        match p.variant {
            Variant::Local => {
                f.push(Field::text("API base", &p.api_base));
            }
            Variant::Hybrid => {
                f.push(Field::text("URL local", &p.local_url));
                f.push(Field::select(
                    "Backend",
                    &p.backend,
                    vec!["auto", "local", "groq", "remote"],
                ));
                f.push(Field::select(
                    "Proveedor cloud",
                    &p.cloud_provider,
                    CLOUD_PROVIDER_OPTIONS.to_vec(),
                ));
                f.push(Field::select(
                    "Preset cloud",
                    cloud_preset_value(&p.cloud_provider, &p.remote_model),
                    cloud_model_options(&p.cloud_provider),
                ));
                f.push(Field::bool("Critic mode", p.critic));
                f.push(Field::text("Modelo Groq", &p.groq_model));
                f.push(Field::text("URL cloud", &p.remote_url));
                f.push(Field::text("Modelo cloud", &p.remote_model));
                f.push(Field::text("API key cloud", &p.remote_api_key));
                f.push(Field::select(
                    "Sandbox",
                    profile_select_value(&p.sandbox),
                    vec!["off", "docker"],
                ));
                f.push(Field::text("Sandbox image", &p.sandbox_image));
            }
        }
        self.fields = f;
        self.field_idx = self.field_idx.min(self.fields.len().saturating_sub(1));
        self.refresh_configure_preview();
    }

    pub fn sync_profile(&mut self) {
        for f in &self.fields {
            match f.label {
                "Perfil" => self.profile.name = f.value.clone(),
                "GPU" => self.profile.gpu_profile = f.value.clone(),
                "GPU preset" => self.profile.gpu_preset = f.value.clone(),
                "Modelo" => self.profile.model = f.value.clone(),
                "Project Root" => self.profile.work_dir = f.value.clone(),
                "Tag" => self.profile.tag = f.value.clone(),
                "Contexto" => self.profile.ctx = f.value.parse().unwrap_or(self.profile.ctx),
                "Temperatura" => {
                    self.profile.temperature = f.value.parse().unwrap_or(self.profile.temperature)
                }
                "Prompt sistema" => self.profile.system_prompt = f.value.clone(),
                "Read only" => self.profile.read_only = f.value == "on",
                "Guided mode" => self.profile.guided_mode = f.value == "on",
                "API base" => self.profile.api_base = f.value.clone(),
                "URL local" => self.profile.local_url = f.value.clone(),
                "Backend" => self.profile.backend = f.value.clone(),
                "Proveedor cloud" => self.profile.cloud_provider = f.value.clone(),
                "Preset cloud" => {
                    if f.value != "custom" {
                        self.profile.remote_model = f.value.clone();
                    }
                }
                "Critic mode" => self.profile.critic = f.value == "on",
                "Modelo Groq" => self.profile.groq_model = f.value.clone(),
                "URL cloud" => self.profile.remote_url = f.value.clone(),
                "Modelo cloud" => self.profile.remote_model = f.value.clone(),
                "API key cloud" => self.profile.remote_api_key = f.value.clone(),
                "Sandbox" => {
                    self.profile.sandbox = if f.value == "off" {
                        String::new()
                    } else {
                        f.value.clone()
                    }
                }
                "Sandbox image" => self.profile.sandbox_image = f.value.clone(),
                _ => {}
            }
        }
        self.refresh_configure_preview();
    }

    pub fn save_profile(&mut self) {
        self.sync_profile();
        self.store.upsert(self.profile.clone());
        match self.store.save() {
            Ok(()) => self.set_status(format!("Perfil '{}' guardado.", self.profile.name), false),
            Err(e) => self.set_status(format!("Error al guardar: {e}"), true),
        }
    }

    pub fn run_preflight(&mut self) -> PreflightReport {
        self.sync_profile();
        let report = preflight::run(&self.profile);
        let has_blockers = report.has_blockers();
        self.preflight_report = Some(report.clone());
        self.set_status(
            if has_blockers {
                "Preflight: se detectaron bloqueos reales.".into()
            } else {
                "Preflight: configuración lista.".into()
            },
            has_blockers,
        );
        self.refresh_configure_preview();
        report
    }

    pub fn launch_session(&mut self) {
        self.sync_profile();
        if self.profile.model.trim().is_empty() {
            self.set_status("El modelo no puede estar vacio.".into(), true);
            return;
        }
        let report = self.run_preflight();
        if report.has_blockers() {
            self.set_status(
                "Preflight con errores: corrige la configuración antes de lanzar.".into(),
                true,
            );
            return;
        }
        self.session_command_preview =
            crate::agent::command_preview(&self.profile, &self.repo_root);
        self.session_work_dir_preview =
            resolve_path_for_display(&self.profile.work_dir, &self.repo_root);
        match AgentSession::spawn(&self.profile, &self.repo_root) {
            Ok(mut session) => {
                session.lines.push_back(format!(
                    "[launcher] Sesion iniciada: {} Â· {}",
                    self.profile.variant.label(),
                    self.profile.model
                ));
                self.last_session_lines.clear();
                self.last_session_tools.clear();
                self.session = Some(session);
                self.screen = Screen::Session;
                self.input_buffer.clear();
                self.input_cursor = 0;
                self.session_scroll = 0;
                self.session_follow_output = true;
                self.set_status("Agente en ejecucion.".into(), false);
            }
            Err(err) => self.set_status(format!("No se pudo lanzar el agente: {err}"), true),
        }
    }

    pub fn poll_session(&mut self) -> bool {
        let mut changed = false;
        let mut finished_lines: Option<VecDeque<String>> = None;
        let mut finished_tools: Option<VecDeque<RecentTool>> = None;
        let mut status_update: Option<(String, bool)> = None;

        if let Some(session) = self.session.as_mut() {
            if let Some(exit) = session.drain_events() {
                changed = true;
                match exit {
                    Ok(status) if status.success() => {
                        session
                            .lines
                            .push_back("[launcher] Proceso finalizado correctamente.".into());
                        status_update = Some(("La sesion termino correctamente.".into(), false));
                    }
                    Ok(status) => {
                        session.lines.push_back(format!(
                            "[launcher] Proceso finalizado con codigo: {status}"
                        ));
                        status_update = Some(("La sesion termino con error.".into(), true));
                    }
                    Err(err) => {
                        session
                            .lines
                            .push_back(format!("[launcher] Error al esperar el proceso: {err}"));
                        status_update =
                            Some(("Fallo al gestionar el proceso del agente.".into(), true));
                    }
                }
                finished_lines = Some(session.lines.clone());
                finished_tools = Some(session.recent_tools.clone());
            } else if !session.lines.is_empty() {
                changed = session.last_event_changed();
            }
        }

        if changed && self.session_follow_output {
            self.session_scroll = 0;
        }
        if let Some(lines) = finished_lines {
            self.last_session_lines = lines;
            self.last_session_tools = finished_tools.unwrap_or_default();
            self.session = None;
            changed = true;
        }
        if let Some((msg, is_err)) = status_update {
            self.set_status(msg, is_err);
            changed = true;
        }
        changed
    }

    pub fn poll_models(&mut self) -> bool {
        let mut changed = false;
        while let Some(event) = self.model_task.as_ref().and_then(|task| task.try_recv()) {
            changed = true;
            match event {
                ModelEvent::Status(msg) => {
                    self.model_progress = None;
                    self.push_model_log(msg.clone());
                    self.set_status(msg, false);
                }
                ModelEvent::Progress(msg) => {
                    self.model_progress = Some(msg.clone());
                    self.set_status(msg, false);
                }
                ModelEvent::Listed(result) => {
                    self.model_task = None;
                    self.model_task_running = false;
                    self.model_progress = None;
                    match result {
                        Ok(models) => {
                            let names: Vec<String> =
                                models.iter().map(|model| model.name.clone()).collect();
                            self.models = models;
                            self.model_idx = names
                                .iter()
                                .position(|name| name == &self.profile.model)
                                .unwrap_or(0)
                                .min(self.models.len().saturating_sub(1));
                            self.push_model_log(format!(
                                "Modelos disponibles: {}",
                                self.models.len()
                            ));
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
                    self.model_progress = None;
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
        changed
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
        if let Some(name) = self
            .store
            .profiles
            .get(self.profile_idx)
            .map(|p| p.name.clone())
        {
            self.store.remove(&name);
            let _ = self.store.save();
            self.profile_idx = self.profile_idx.saturating_sub(1);
            self.set_status(format!("Perfil '{name}' eliminado."), false);
        }
    }

    pub fn set_status(&mut self, msg: String, is_err: bool) {
        self.status = Some((msg, is_err));
    }

    pub fn poll_timeout(&self) -> Duration {
        // Foreground interaction should feel snappy while a session or model
        // task is active, but the launcher can sleep longer when fully idle.
        if self.session.is_some() || self.model_task_running {
            Duration::from_millis(25)
        } else {
            Duration::from_millis(120)
        }
    }

    pub fn local_models_endpoint(&self) -> Result<String, String> {
        native_api_base(self.profile.local_management_base())
    }

    pub fn selected_model(&self) -> Option<&InstalledModel> {
        self.models.get(self.model_idx)
    }

    pub fn session_window_text(&self, height: u16) -> String {
        let window = height.max(1) as usize;
        let lines = self.session_lines();
        if lines.is_empty() {
            return "[launcher] No hay salida todavia.".into();
        }
        // Render only the visible tail/window instead of the whole retained
        // session history. This keeps redraw cost bounded as logs grow.
        let (start, len) = visible_window_bounds(lines.len(), window, self.session_scroll as usize);
        lines
            .iter()
            .skip(start)
            .take(len)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    }

    pub fn session_view_label(&self) -> String {
        match (
            self.session.is_some(),
            self.session_follow_output,
            self.session_scroll,
        ) {
            (true, true, _) => " Live Output · following ".into(),
            (true, false, n) if n > 0 => format!(" Live Output · +{n} "),
            (true, false, _) => " Live Output ".into(),
            (false, _, _) => " Last Session ".into(),
        }
    }

    pub fn session_scrollbar_metrics(&self, height: u16) -> Option<(usize, usize, usize)> {
        let window = height.max(1) as usize;
        let lines = self.session_lines();
        if lines.len() <= window {
            return None;
        }
        let (start, len) = visible_window_bounds(lines.len(), window, self.session_scroll as usize);
        Some((lines.len(), start, len))
    }

    pub fn model_window_text(&self, height: u16) -> String {
        let mut combined: Vec<&str> = self.model_logs.iter().map(String::as_str).collect();
        if let Some(progress) = self.model_progress.as_deref() {
            combined.push(progress);
        }
        if combined.is_empty() {
            return "Sin actividad todavia.".into();
        }
        let window = height.max(1) as usize;
        let start = combined.len().saturating_sub(window);
        combined
            .into_iter()
            .skip(start)
            .collect::<Vec<_>>()
            .join("\n")
    }

    pub fn recent_tools_text(&self, height: u16) -> String {
        let tools = if let Some(session) = self.session.as_ref() {
            &session.recent_tools
        } else {
            &self.last_session_tools
        };
        if tools.is_empty() {
            return "Sin tools recientes.".into();
        }
        let window = height.max(1) as usize;
        let start = tools.len().saturating_sub(window);
        tools
            .iter()
            .skip(start)
            .map(|tool| {
                if tool.target.is_empty() {
                    format!("{} -> {}", tool.title, tool.result)
                } else {
                    format!("{} {} -> {}", tool.title, tool.target, tool.result)
                }
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    pub fn session_meta_text(&self) -> String {
        let preflight = self
            .preflight_report
            .as_ref()
            .map(|report| report.summary_line())
            .unwrap_or_else(|| "preflight: sin ejecutar".into());
        let project_root = resolve_path_for_display(&self.profile.work_dir, &self.repo_root);
        let generic_warning = project_root_warning(&self.profile.work_dir, &self.repo_root)
            .map(|warning| format!("\nwarning: {warning}"))
            .unwrap_or_default();
        format!(
            "{}\nproject root: {}\nworking dir: {}{}\nmodo: {}  guided: {}  {}",
            self.session_command_preview,
            project_root,
            self.session_work_dir_preview,
            generic_warning,
            if self.profile.read_only {
                "read-only"
            } else {
                "read-write"
            },
            if self.profile.guided_mode {
                "on"
            } else {
                "off"
            },
            preflight
        )
    }

    pub fn current_screen_hint(&self) -> &'static str {
        match self.screen {
            Screen::MainMenu => "j/k navegar  Enter abrir  q salir",
            Screen::Configure => "Tab campo  Enter editar  F3 modelos  F4 preset GPU  F5 lanzar  F8 preflight  F2 guardar  Esc volver",
            Screen::Models => "j/k navegar  Enter usar  g recomendado  p pull  d borrar  r refrescar  Esc volver",
            Screen::Profiles => "j/k navegar  Enter cargar  d borrar  Esc volver",
            Screen::Session => "Escribir o /clear  Flechas izq/der editar  F6 detener  F7 ratón  PgUp/PgDn scroll  Esc volver",
        }
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

    pub fn handle_mouse(&mut self, event: MouseEvent, frame_area: Rect) {
        self.status = None;
        if self.screen != Screen::Session || !self.session_mouse_mode {
            return;
        }
        self.on_session_mouse(event, frame_area);
    }

    pub fn wants_mouse_capture(&self) -> bool {
        self.screen == Screen::Session && self.session_mouse_mode
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
        let editing = self
            .fields
            .get(self.field_idx)
            .map(|f| f.editing)
            .unwrap_or(false);
        if editing {
            self.on_configure_editing(code);
        } else {
            self.on_configure_nav(code, mods);
        }
    }

    fn on_configure_editing(&mut self, code: KeyCode) {
        let mut changed = false;
        match code {
            KeyCode::Enter | KeyCode::Esc => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    f.editing = false;
                }
            }
            KeyCode::Backspace => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    changed = f.value.pop().is_some();
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
                        changed = true;
                    }
                }
            }
            _ => {}
        }
        if changed {
            self.refresh_configure_preview();
        }
    }

    fn on_configure_nav(&mut self, code: KeyCode, mods: KeyModifiers) {
        let n = self.fields.len();
        match code {
            KeyCode::Tab | KeyCode::Down => {
                self.field_idx = (self.field_idx + 1).min(n.saturating_sub(1))
            }
            KeyCode::BackTab | KeyCode::Up => self.field_idx = self.field_idx.saturating_sub(1),
            KeyCode::Enter | KeyCode::Char(' ') => {
                if let Some(f) = self.fields.get_mut(self.field_idx) {
                    match f.kind.clone() {
                        FieldKind::Bool => {
                            f.value = if f.value == "on" {
                                "off".into()
                            } else {
                                "on".into()
                            };
                            self.refresh_configure_preview();
                        }
                        FieldKind::Select(opts) => {
                            let current = opts.iter().position(|&o| o == f.value).unwrap_or(0);
                            f.value = opts[(current + 1) % opts.len()].to_string();
                            let selected_label = f.label;
                            let selected_value = f.value.clone();
                            if selected_label == "Proveedor cloud" {
                                self.apply_cloud_provider_defaults(&selected_value);
                                self.rebuild_fields();
                            } else if selected_label == "Preset cloud" {
                                self.apply_cloud_model_preset(&selected_value);
                            }
                            self.refresh_configure_preview();
                        }
                        _ => f.editing = true,
                    }
                }
            }
            KeyCode::F(5) => self.launch_session(),
            KeyCode::F(8) => {
                self.run_preflight();
            }
            KeyCode::F(4) => self.apply_gpu_recommendation(),
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
            KeyCode::Up | KeyCode::Char('k') => {
                self.profile_idx = self.profile_idx.saturating_sub(1)
            }
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
            KeyCode::Char('g') => self.pull_gpu_recommendation(),
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
        match code {
            KeyCode::Char('c') if mods.contains(KeyModifiers::CONTROL) => self.stop_session(),
            KeyCode::F(6) => self.stop_session(),
            KeyCode::F(7) => {
                self.session_mouse_mode = !self.session_mouse_mode;
                self.session_scroll_dragging = false;
                self.set_status(
                    if self.session_mouse_mode {
                        "Modo raton activado: barra arrastrable y rueda activas.".into()
                    } else {
                        "Modo raton desactivado: el terminal vuelve a permitir seleccion y copia."
                            .into()
                    },
                    false,
                );
            }
            KeyCode::Enter => {
                // Session input is always "hot": typing edits the current line
                // immediately and Enter ships it to the managed Python process.
                let line = self.input_buffer.trim().to_string();
                if line.is_empty() {
                    return;
                }
                if self.handle_session_command(&line) {
                    self.input_buffer.clear();
                    self.input_cursor = 0;
                    return;
                }
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
                        self.input_cursor = 0;
                        if self.session_follow_output {
                            self.session_scroll = 0;
                        }
                    }
                    Err(err) => self.set_status(format!("No se pudo enviar entrada: {err}"), true),
                }
            }
            KeyCode::Backspace => {
                self.delete_session_input_before_cursor();
            }
            KeyCode::Delete => {
                self.delete_session_input_at_cursor();
            }
            KeyCode::Char(c)
                if !mods.contains(KeyModifiers::CONTROL) && !mods.contains(KeyModifiers::ALT) =>
            {
                self.insert_session_input(c);
            }
            KeyCode::Left => {
                self.input_cursor = self.input_cursor.saturating_sub(1);
            }
            KeyCode::Right => {
                self.input_cursor = (self.input_cursor + 1).min(self.input_buffer.len());
            }
            KeyCode::Up => {
                self.scroll_session_up(1);
            }
            KeyCode::Down => {
                self.scroll_session_down(1);
            }
            KeyCode::PageUp => {
                self.scroll_session_up(10);
            }
            KeyCode::PageDown => {
                self.scroll_session_down(10);
            }
            KeyCode::Home => {
                self.session_follow_output = false;
                self.session_scroll = u16::MAX;
            }
            KeyCode::End => {
                self.session_scroll = 0;
                self.session_follow_output = true;
            }
            KeyCode::Esc => {
                self.input_buffer.clear();
                self.input_cursor = 0;
                self.session_mouse_mode = false;
                self.session_scroll_dragging = false;
                self.screen = Screen::Configure;
            }
            _ => {}
        }
    }

    fn on_session_mouse(&mut self, event: MouseEvent, frame_area: Rect) {
        let Some(track_area) = self.session_scrollbar_track_area(frame_area) else {
            self.session_scroll_dragging = false;
            return;
        };
        let thumb_area = self.session_scrollbar_thumb_area(frame_area);
        let over_track = rect_contains(track_area, event.column, event.row);
        let over_thumb =
            thumb_area.is_some_and(|area| rect_contains(area, event.column, event.row));

        match event.kind {
            MouseEventKind::ScrollUp => {
                if over_track
                    || self
                        .session_log_area(frame_area)
                        .is_some_and(|area| rect_contains(area, event.column, event.row))
                {
                    self.scroll_session_up(3);
                }
            }
            MouseEventKind::ScrollDown => {
                if over_track
                    || self
                        .session_log_area(frame_area)
                        .is_some_and(|area| rect_contains(area, event.column, event.row))
                {
                    self.scroll_session_down(3);
                }
            }
            MouseEventKind::Down(MouseButton::Left) => {
                if over_thumb {
                    self.session_scroll_dragging = true;
                    self.session_scroll_drag_offset =
                        event.row.saturating_sub(thumb_area.unwrap().y);
                } else if over_track {
                    self.session_scroll_dragging = false;
                    self.session_scroll_drag_offset = 0;
                    self.set_session_scroll_from_track_row(event.row, track_area, 0);
                }
            }
            MouseEventKind::Drag(MouseButton::Left) => {
                if self.session_scroll_dragging {
                    self.set_session_scroll_from_track_row(
                        event.row,
                        track_area,
                        self.session_scroll_drag_offset,
                    );
                }
            }
            MouseEventKind::Up(MouseButton::Left) => {
                self.session_scroll_dragging = false;
                self.session_scroll_drag_offset = 0;
            }
            _ => {}
        }
    }

    fn scroll_session_up(&mut self, amount: u16) {
        if amount == 0 {
            return;
        }
        // Leaving follow mode is explicit: as soon as the user scrolls up,
        // new output stops forcing the view back to the bottom.
        self.session_follow_output = false;
        self.session_scroll = self.session_scroll.saturating_add(amount);
    }

    fn scroll_session_down(&mut self, amount: u16) {
        if amount == 0 {
            return;
        }
        self.session_scroll = self.session_scroll.saturating_sub(amount);
        if self.session_scroll == 0 {
            self.session_follow_output = true;
        }
    }

    fn session_log_area(&self, frame_area: Rect) -> Option<Rect> {
        let [_, body, _] = Layout::vertical([
            Constraint::Length(2),
            Constraint::Min(0),
            Constraint::Length(2),
        ])
        .areas(frame_area);
        let [_, log_area, _] = Layout::vertical([
            Constraint::Length(4),
            Constraint::Min(4),
            Constraint::Length(3),
        ])
        .areas(body);
        if log_area.width < 2 || log_area.height < 3 {
            None
        } else {
            Some(log_area)
        }
    }

    fn session_scrollbar_track_area(&self, frame_area: Rect) -> Option<Rect> {
        let log_area = self.session_log_area(frame_area)?;
        let visible_log_height = log_area.height.saturating_sub(2);
        self.session_scrollbar_metrics(visible_log_height)?;
        Some(Rect {
            x: log_area.x + log_area.width.saturating_sub(1),
            y: log_area.y + 1,
            width: 1,
            height: visible_log_height.max(1),
        })
    }

    fn session_scrollbar_thumb_area(&self, frame_area: Rect) -> Option<Rect> {
        let track_area = self.session_scrollbar_track_area(frame_area)?;
        let (_, thumb_start, thumb_len) =
            self.session_scrollbar_thumb_metrics(track_area.height)?;
        Some(Rect {
            x: track_area.x,
            y: track_area.y + thumb_start,
            width: track_area.width,
            height: thumb_len,
        })
    }

    fn session_scrollbar_thumb_metrics(&self, track_height: u16) -> Option<(usize, u16, u16)> {
        let (total, start, viewport) = self.session_scrollbar_metrics(track_height)?;
        let track_len = track_height.max(1) as usize;
        let max_start = total.saturating_sub(viewport);
        let thumb_len = ((track_len * viewport).max(total) / total)
            .max(1)
            .min(track_len);
        let travel = track_len.saturating_sub(thumb_len);
        let thumb_start = if max_start == 0 || travel == 0 {
            0
        } else {
            ((start * travel) / max_start) as u16
        };
        Some((max_start, thumb_start, thumb_len as u16))
    }

    fn set_session_scroll_from_track_row(&mut self, row: u16, track_area: Rect, drag_offset: u16) {
        let Some((max_start, _, thumb_len)) =
            self.session_scrollbar_thumb_metrics(track_area.height)
        else {
            self.session_scroll = 0;
            self.session_follow_output = true;
            return;
        };
        let track_len = track_area.height.max(1) as usize;
        let travel = track_len.saturating_sub(thumb_len as usize);
        if max_start == 0 || travel == 0 {
            self.session_scroll = 0;
            self.session_follow_output = true;
            return;
        }

        let top_row = row.saturating_sub(drag_offset);
        let max_top = track_area.y + track_area.height.saturating_sub(thumb_len);
        let clamped_top = top_row.clamp(track_area.y, max_top);
        let relative_top = clamped_top.saturating_sub(track_area.y) as usize;
        let start = (relative_top * max_start + (travel / 2)) / travel;
        let scroll_from_bottom = max_start.saturating_sub(start);
        self.session_scroll = scroll_from_bottom.min(u16::MAX as usize) as u16;
        self.session_follow_output = self.session_scroll == 0;
    }

    fn insert_session_input(&mut self, c: char) {
        self.input_buffer.insert(self.input_cursor, c);
        self.input_cursor += c.len_utf8();
    }

    fn handle_session_command(&mut self, line: &str) -> bool {
        match line.trim() {
            "/clear" | "/reset" => {
                self.restart_session_with_clean_chat();
                true
            }
            "/help" => {
                if let Some(session) = self.session.as_mut() {
                    session
                        .lines
                        .push_back("[launcher] Comandos locales: /clear, /reset, /help".into());
                } else {
                    self.last_session_lines
                        .push_back("[launcher] Comandos locales: /clear, /reset, /help".into());
                }
                self.set_status("Mostrando ayuda de comandos locales.".into(), false);
                true
            }
            _ => false,
        }
    }

    fn restart_session_with_clean_chat(&mut self) {
        if let Some(mut session) = self.session.take() {
            let _ = session.stop();
        }
        self.last_session_lines.clear();
        self.input_buffer.clear();
        self.input_cursor = 0;
        self.session_scroll = 0;
        self.session_follow_output = true;
        self.session_scroll_dragging = false;
        self.launch_session();
        if let Some(session) = self.session.as_mut() {
            session
                .lines
                .push_back("[launcher] Conversacion reiniciada con /clear.".into());
        }
    }

    fn delete_session_input_before_cursor(&mut self) {
        if self.input_cursor == 0 || self.input_buffer.is_empty() {
            return;
        }
        let prev = self.input_buffer[..self.input_cursor]
            .char_indices()
            .last()
            .map(|(idx, _)| idx)
            .unwrap_or(0);
        self.input_buffer.drain(prev..self.input_cursor);
        self.input_cursor = prev;
    }

    fn delete_session_input_at_cursor(&mut self) {
        if self.input_cursor >= self.input_buffer.len() || self.input_buffer.is_empty() {
            return;
        }
        let next = self.input_buffer[self.input_cursor..]
            .char_indices()
            .nth(1)
            .map(|(idx, _)| self.input_cursor + idx)
            .unwrap_or(self.input_buffer.len());
        self.input_buffer.drain(self.input_cursor..next);
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
                self.model_progress = None;
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
                self.model_progress = None;
                self.push_model_log(format!("Descargando '{requested}'..."));
            }
            Err(err) => {
                self.push_model_log(err.clone());
                self.set_status(err, true);
            }
        }
    }

    fn pull_gpu_recommendation(&mut self) {
        self.sync_profile();
        let rec = gpu_recommendation(
            &self.profile.gpu_profile,
            &self.profile.gpu_preset,
            &self.profile.variant,
        );
        if rec.label == "custom" || rec.model.is_empty() {
            self.set_status(
                "Selecciona una GPU concreta para instalar un modelo recomendado.".into(),
                true,
            );
            return;
        }
        self.model_input_buffer = rec.model.into();
        self.pull_model();
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
                self.model_progress = None;
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
            // Keep a short retained history; long-lived progress spam belongs
            // in the live progress line, not in an ever-growing log buffer.
            self.model_logs.remove(0);
        }
        self.model_logs.push(line);
    }

    pub fn gpu_recommendation_summary(&self) -> String {
        gpu_recommendation_summary_for(&self.profile)
    }

    fn apply_gpu_recommendation(&mut self) {
        self.sync_profile();
        let rec = gpu_recommendation(
            &self.profile.gpu_profile,
            &self.profile.gpu_preset,
            &self.profile.variant,
        );
        if rec.label == "custom" {
            self.set_status(
                "Perfil GPU en custom: no se aplican cambios automaticos.".into(),
                false,
            );
            return;
        }
        self.profile.model = rec.model.into();
        self.profile.ctx = rec.ctx;
        self.rebuild_fields();
        self.set_status(
            format!(
                "Preset RTX {} [{}] aplicado: modelo '{}' y ctx {}.",
                rec.label, rec.preset, rec.model, rec.ctx
            ),
            false,
        );
    }

    fn session_lines(&self) -> &VecDeque<String> {
        if let Some(session) = self.session.as_ref() {
            &session.lines
        } else {
            &self.last_session_lines
        }
    }

    fn preview_profile(&self) -> Profile {
        let mut preview = self.profile.clone();
        for f in &self.fields {
            match f.label {
                "Perfil" => preview.name = f.value.clone(),
                "GPU" => preview.gpu_profile = f.value.clone(),
                "GPU preset" => preview.gpu_preset = f.value.clone(),
                "Modelo" => preview.model = f.value.clone(),
                "Project Root" => preview.work_dir = f.value.clone(),
                "Tag" => preview.tag = f.value.clone(),
                "Contexto" => preview.ctx = f.value.parse().unwrap_or(preview.ctx),
                "Temperatura" => {
                    preview.temperature = f.value.parse().unwrap_or(preview.temperature)
                }
                "Prompt sistema" => preview.system_prompt = f.value.clone(),
                "Read only" => preview.read_only = f.value == "on",
                "Guided mode" => preview.guided_mode = f.value == "on",
                "API base" => preview.api_base = f.value.clone(),
                "URL local" => preview.local_url = f.value.clone(),
                "Backend" => preview.backend = f.value.clone(),
                "Proveedor cloud" => preview.cloud_provider = f.value.clone(),
                "Preset cloud" => {
                    if f.value != "custom" {
                        preview.remote_model = f.value.clone();
                    }
                }
                "Critic mode" => preview.critic = f.value == "on",
                "Modelo Groq" => preview.groq_model = f.value.clone(),
                "URL cloud" => preview.remote_url = f.value.clone(),
                "Modelo cloud" => preview.remote_model = f.value.clone(),
                "API key cloud" => preview.remote_api_key = f.value.clone(),
                "Sandbox" => {
                    preview.sandbox = if f.value == "off" {
                        String::new()
                    } else {
                        f.value.clone()
                    }
                }
                "Sandbox image" => preview.sandbox_image = f.value.clone(),
                _ => {}
            }
        }
        preview
    }

    fn refresh_configure_preview(&mut self) {
        let preview = self.preview_profile();
        self.configure_preview_command = crate::agent::command_preview(&preview, &self.repo_root);
        let preflight_summary = self
            .preflight_report
            .as_ref()
            .map(|report| report.summary_line())
            .unwrap_or_else(|| "preflight: pendiente".into());
        self.configure_preview_detail = match preview.variant {
            Variant::Local => format!(
                "project root: {}  modo: {}  guided: {}  {}  {}{}",
                resolve_path_for_display(&preview.work_dir, &self.repo_root),
                if preview.read_only {
                    "read-only"
                } else {
                    "read-write"
                },
                if preview.guided_mode { "on" } else { "off" },
                preflight_summary,
                gpu_recommendation_summary_for(&preview),
                project_root_warning(&preview.work_dir, &self.repo_root)
                    .map(|warning| format!("\nwarning: {warning}"))
                    .unwrap_or_default()
            ),
            Variant::Hybrid => {
                format!(
                "project root: {}\nbackend: {}  cloud: {}  key: {}  critic: {}  sandbox: {}  modo: {}  guided: {}  {}  {}{}",
                resolve_path_for_display(&preview.work_dir, &self.repo_root),
                preview.backend,
                hybrid_cloud_summary(&preview),
                if preview.remote_api_key.trim().is_empty() { "env/off" } else { "inline" },
                if preview.critic { "on" } else { "off" },
                if preview.sandbox.is_empty() { "off" } else { &preview.sandbox },
                if preview.read_only { "read-only" } else { "read-write" },
                if preview.guided_mode { "on" } else { "off" },
                preflight_summary,
                gpu_recommendation_summary_for(&preview),
                project_root_warning(&preview.work_dir, &self.repo_root)
                    .map(|warning| format!("\nwarning: {warning}"))
                    .unwrap_or_default()
            )
            }
        };
    }

    fn apply_cloud_provider_defaults(&mut self, provider: &str) {
        let defaults = cloud_provider_defaults(provider);
        if provider == "none" {
            self.set_field_value("Preset cloud", "custom");
            self.set_field_value("URL cloud", "");
            self.set_field_value("Modelo cloud", "");
            if self.profile.backend == "remote" {
                self.set_field_value("Backend", "auto");
            }
            return;
        }

        if !defaults.url.is_empty() {
            self.set_field_value("URL cloud", defaults.url);
        }
        if !defaults.model.is_empty() {
            self.set_field_value("Preset cloud", defaults.model);
            self.set_field_value("Modelo cloud", defaults.model);
        }
        if provider == "groq" {
            self.set_field_value("Modelo Groq", defaults.model);
            if self.profile.backend == "remote" || self.profile.backend == "auto" {
                self.set_field_value("Backend", "groq");
            }
        } else if self.profile.backend == "groq" || self.profile.backend == "auto" {
            self.set_field_value("Backend", "remote");
        }
    }

    fn apply_cloud_model_preset(&mut self, preset: &str) {
        if preset == "custom" {
            return;
        }
        self.set_field_value("Modelo cloud", preset);
        if self.profile.backend == "auto" {
            self.set_field_value("Backend", "remote");
        }
    }

    fn set_field_value(&mut self, label: &str, value: &str) {
        if let Some(field) = self.fields.iter_mut().find(|field| field.label == label) {
            field.value = value.to_string();
        }
        match label {
            "Backend" => self.profile.backend = value.to_string(),
            "Proveedor cloud" => self.profile.cloud_provider = value.to_string(),
            "Preset cloud" => {}
            "URL cloud" => self.profile.remote_url = value.to_string(),
            "Modelo cloud" => self.profile.remote_model = value.to_string(),
            "Modelo Groq" => self.profile.groq_model = value.to_string(),
            _ => {}
        }
    }
}

struct GpuRecommendation {
    label: &'static str,
    preset: &'static str,
    model: &'static str,
    ctx: u32,
}

fn gpu_recommendation(gpu_profile: &str, gpu_preset: &str, variant: &Variant) -> GpuRecommendation {
    match (gpu_profile, gpu_preset, variant) {
        ("5060", "safe", Variant::Local) | ("5060", "safe", Variant::Hybrid) => GpuRecommendation {
            label: "5060",
            preset: "safe",
            model: "qwen2.5-coder:3b",
            ctx: 2048,
        },
        ("5060", "balanced", Variant::Local) | ("5060", "balanced", Variant::Hybrid) => {
            GpuRecommendation {
                label: "5060",
                preset: "balanced",
                model: "qwen2.5-coder:7b",
                ctx: 4096,
            }
        }
        ("5060", "max", Variant::Local) | ("5060", "max", Variant::Hybrid) => GpuRecommendation {
            label: "5060",
            preset: "max",
            model: "qwen2.5-coder:7b",
            ctx: 8192,
        },
        ("5070", "safe", Variant::Local) | ("5070", "safe", Variant::Hybrid) => GpuRecommendation {
            label: "5070",
            preset: "safe",
            model: "qwen2.5-coder:7b",
            ctx: 8192,
        },
        ("5070", "balanced", Variant::Local) | ("5070", "balanced", Variant::Hybrid) => {
            GpuRecommendation {
                label: "5070",
                preset: "balanced",
                model: "qwen2.5-coder:14b",
                ctx: 8192,
            }
        }
        ("5070", "max", Variant::Local) | ("5070", "max", Variant::Hybrid) => GpuRecommendation {
            label: "5070",
            preset: "max",
            model: "qwen2.5-coder:14b",
            ctx: 12288,
        },
        ("5080", "safe", Variant::Local) | ("5080", "safe", Variant::Hybrid) => GpuRecommendation {
            label: "5080",
            preset: "safe",
            model: "qwen2.5-coder:14b",
            ctx: 8192,
        },
        ("5080", "balanced", Variant::Local) | ("5080", "balanced", Variant::Hybrid) => {
            GpuRecommendation {
                label: "5080",
                preset: "balanced",
                model: "qwen2.5-coder:32b",
                ctx: 8192,
            }
        }
        ("5080", "max", Variant::Local) | ("5080", "max", Variant::Hybrid) => GpuRecommendation {
            label: "5080",
            preset: "max",
            model: "qwen2.5-coder:32b",
            ctx: 16384,
        },
        ("5090", "safe", Variant::Local) | ("5090", "safe", Variant::Hybrid) => GpuRecommendation {
            label: "5090",
            preset: "safe",
            model: "qwen2.5-coder:14b",
            ctx: 16384,
        },
        ("5090", "balanced", Variant::Local) | ("5090", "balanced", Variant::Hybrid) => {
            GpuRecommendation {
                label: "5090",
                preset: "balanced",
                model: "qwen2.5-coder:32b",
                ctx: 16384,
            }
        }
        ("5090", "max", Variant::Local) | ("5090", "max", Variant::Hybrid) => GpuRecommendation {
            label: "5090",
            preset: "max",
            model: "qwen2.5-coder:32b",
            ctx: 32768,
        },
        _ => GpuRecommendation {
            label: "custom",
            preset: "custom",
            model: "",
            ctx: 0,
        },
    }
}

fn profile_select_value(value: &str) -> &str {
    if value.trim().is_empty() {
        "off"
    } else {
        value
    }
}

struct CloudProviderDefaults {
    url: &'static str,
    model: &'static str,
}

fn cloud_provider_defaults(provider: &str) -> CloudProviderDefaults {
    match provider {
        "groq" => CloudProviderDefaults {
            url: "https://api.groq.com/openai/v1",
            model: "llama-3.3-70b-versatile",
        },
        "openai" => CloudProviderDefaults {
            url: "https://api.openai.com/v1",
            model: "gpt-4.1-mini",
        },
        "openrouter" => CloudProviderDefaults {
            url: "https://openrouter.ai/api/v1",
            model: "openai/gpt-4.1-mini",
        },
        "custom" => CloudProviderDefaults { url: "", model: "" },
        _ => CloudProviderDefaults { url: "", model: "" },
    }
}

fn hybrid_cloud_summary(profile: &Profile) -> String {
    match profile.backend.as_str() {
        "groq" => format!("groq/{}", profile.groq_model),
        "remote" => {
            let provider = if profile.cloud_provider.trim().is_empty() {
                "custom"
            } else {
                &profile.cloud_provider
            };
            let model = if profile.remote_model.trim().is_empty() {
                "(sin modelo)"
            } else {
                &profile.remote_model
            };
            format!("{provider}/{model}")
        }
        _ => profile.cloud_provider.clone(),
    }
}

fn cloud_model_options(provider: &str) -> Vec<&'static str> {
    match provider {
        "groq" => vec![
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "qwen/qwen3-32b",
            "moonshotai/kimi-k2-instruct-0905",
            "openai/gpt-oss-120b",
            "custom",
        ],
        "openai" => vec![
            "gpt-5.1",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4.1",
            "custom",
        ],
        "openrouter" => vec![
            "openrouter/auto",
            "openai/gpt-5-mini",
            "openai/gpt-5-nano",
            "openai/gpt-4.1",
            "openai/gpt-5.4-mini",
            "custom",
        ],
        _ => vec!["custom"],
    }
}

fn cloud_preset_value(provider: &str, remote_model: &str) -> &'static str {
    for option in cloud_model_options(provider) {
        if option == remote_model {
            return option;
        }
    }
    "custom"
}

fn visible_window_bounds(total: usize, window: usize, scroll_from_bottom: usize) -> (usize, usize) {
    let window = window.max(1);
    if total == 0 {
        return (0, 0);
    }
    // Scroll is tracked from the bottom because that matches the default
    // "follow output" behavior of a terminal session better than top-based
    // offsets.
    let max_start = total.saturating_sub(window);
    let start = max_start.saturating_sub(scroll_from_bottom.min(max_start));
    let len = (total - start).min(window);
    (start, len)
}

fn gpu_recommendation_summary_for(profile: &Profile) -> String {
    let rec = gpu_recommendation(&profile.gpu_profile, &profile.gpu_preset, &profile.variant);
    if rec.label == "custom" {
        "gpu: custom".into()
    } else {
        format!(
            "gpu: RTX {} [{}] -> {} / ctx {}",
            rec.label, rec.preset, rec.model, rec.ctx
        )
    }
}

fn resolve_path_for_display(path: &str, repo_root: &Path) -> String {
    let raw = PathBuf::from(path);
    let resolved = if path.trim().is_empty() || path.trim() == "." {
        repo_root.to_path_buf()
    } else if raw.is_absolute() {
        raw
    } else {
        repo_root.join(raw)
    };
    resolved.to_string_lossy().to_string()
}

fn project_root_warning(path: &str, repo_root: &Path) -> Option<String> {
    let resolved = PathBuf::from(resolve_path_for_display(path, repo_root));
    let home = dirs::home_dir();
    let generic_names = [
        "documents",
        "documentos",
        "desktop",
        "escritorio",
        "downloads",
        "descargas",
        "onedrive",
        "dropbox",
        "icloud drive",
        "my documents",
        "mis documentos",
    ];
    let is_generic = home
        .as_ref()
        .map(|candidate| candidate == &resolved)
        .unwrap_or(false)
        || generic_names
            .iter()
            .any(|name| resolved.file_name().map(|part| part.to_string_lossy().eq_ignore_ascii_case(name)).unwrap_or(false));
    if is_generic {
        Some(
            "esta carpeta parece demasiado genérica; usa la raíz real de un proyecto para mejores resultados"
                .into(),
        )
    } else {
        None
    }
}

fn rect_contains(area: Rect, x: u16, y: u16) -> bool {
    x >= area.x
        && x < area.x.saturating_add(area.width)
        && y >= area.y
        && y < area.y.saturating_add(area.height)
}

#[cfg(test)]
mod tests {
    use super::{
        cloud_model_options, cloud_preset_value, cloud_provider_defaults, gpu_recommendation,
        project_root_warning, resolve_path_for_display, visible_window_bounds,
    };
    use crate::config::Variant;
    use std::path::{Path, PathBuf};

    #[test]
    fn gpu_recommendation_5060_safe_is_conservative() {
        let rec = gpu_recommendation("5060", "safe", &Variant::Local);
        assert_eq!(rec.model, "qwen2.5-coder:3b");
        assert_eq!(rec.ctx, 2048);
    }

    #[test]
    fn gpu_recommendation_5090_max_allows_larger_context() {
        let rec = gpu_recommendation("5090", "max", &Variant::Hybrid);
        assert_eq!(rec.model, "qwen2.5-coder:32b");
        assert_eq!(rec.ctx, 32768);
    }

    #[test]
    fn resolve_relative_work_dir_for_preview() {
        let repo = Path::new("/repo");
        assert_eq!(resolve_path_for_display(".", repo), "/repo");
    }

    #[test]
    fn generic_project_root_warning_flags_documents_folder() {
        let repo = Path::new("/repo");
        let warning = project_root_warning("/Users/dev/Documents", repo);
        assert!(warning.is_some());
    }

    #[test]
    fn generic_project_root_warning_ignores_normal_repo_folder() {
        let repo = PathBuf::from("/workspace");
        let warning = project_root_warning("/workspace/my-app", &repo);
        assert!(warning.is_none());
    }

    #[test]
    fn visible_window_follows_bottom_by_default() {
        assert_eq!(visible_window_bounds(10, 4, 0), (6, 4));
    }

    #[test]
    fn visible_window_scrolls_up_from_bottom() {
        assert_eq!(visible_window_bounds(10, 4, 2), (4, 4));
    }

    #[test]
    fn openai_provider_defaults_fill_known_endpoint() {
        let defaults = cloud_provider_defaults("openai");
        assert_eq!(defaults.url, "https://api.openai.com/v1");
        assert_eq!(defaults.model, "gpt-4.1-mini");
    }

    #[test]
    fn groq_provider_defaults_keep_groq_model() {
        let defaults = cloud_provider_defaults("groq");
        assert_eq!(defaults.url, "https://api.groq.com/openai/v1");
        assert_eq!(defaults.model, "llama-3.3-70b-versatile");
    }

    #[test]
    fn openai_model_options_include_fast_and_strong_variants() {
        let options = cloud_model_options("openai");
        assert!(options.contains(&"gpt-5.1"));
        assert!(options.contains(&"gpt-5-mini"));
    }

    #[test]
    fn unknown_cloud_model_maps_to_custom_preset() {
        assert_eq!(cloud_preset_value("openai", "my-own-model"), "custom");
    }
}
