//! Local model management against the local backend.
//!
//! This module talks to the backend that already powers local inference. Model
//! management is only available when that endpoint also exposes Ollama's native
//! `/api/*` routes such as `/api/tags`, `/api/pull`, and `/api/delete`.

use crate::config::Profile;
use serde::Deserialize;
use serde_json::json;
use std::io::{BufRead, BufReader};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;

#[derive(Debug, Clone, Default)]
pub struct InstalledModel {
    pub name: String,
    pub size_bytes: Option<u64>,
    pub modified_at: Option<String>,
}

#[derive(Debug)]
pub enum ModelEvent {
    Status(String),
    Progress(String),
    Listed(Result<Vec<InstalledModel>, String>),
    Finished(Result<String, String>),
}

pub struct ModelTask {
    rx: Receiver<ModelEvent>,
}

impl ModelTask {
    pub fn spawn_refresh(profile: &Profile) -> Result<Self, String> {
        let base = native_api_base(profile.local_management_base())?;
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let _ = tx.send(ModelEvent::Status(format!("Consultando modelos en {base}...")));
            let result = list_models(&base);
            let _ = tx.send(ModelEvent::Listed(result));
        });
        Ok(Self { rx })
    }

    pub fn spawn_delete(profile: &Profile, model: String) -> Result<Self, String> {
        let base = native_api_base(profile.local_management_base())?;
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let _ = tx.send(ModelEvent::Status(format!("Borrando modelo '{model}'...")));
            let result = delete_model(&base, &model);
            let _ = tx.send(ModelEvent::Finished(result));
        });
        Ok(Self { rx })
    }

    pub fn spawn_pull(profile: &Profile, model: String) -> Result<Self, String> {
        let base = native_api_base(profile.local_management_base())?;
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let result = pull_model(&base, &model, &tx);
            let _ = tx.send(ModelEvent::Finished(result));
        });
        Ok(Self { rx })
    }

    pub fn try_recv(&self) -> Option<ModelEvent> {
        self.rx.try_recv().ok()
    }
}

#[derive(Debug, Deserialize)]
struct TagsResponse {
    #[serde(default)]
    models: Vec<TagEntry>,
}

#[derive(Debug, Deserialize)]
struct TagEntry {
    name: String,
    #[serde(default)]
    size: Option<u64>,
    #[serde(default)]
    modified_at: Option<String>,
}

#[derive(Debug, Deserialize)]
struct PullLine {
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    error: Option<String>,
    #[serde(default)]
    total: Option<u64>,
    #[serde(default)]
    completed: Option<u64>,
}

pub fn native_api_base(openai_base: &str) -> Result<String, String> {
    let trimmed = openai_base.trim();
    if trimmed.is_empty() {
        return Err("La URL del backend local estA vacia.".into());
    }
    let normalized = trimmed.trim_end_matches('/');
    let native = normalized
        .strip_suffix("/v1")
        .unwrap_or(normalized)
        .trim_end_matches('/')
        .to_string();
    if native.starts_with("http://") || native.starts_with("https://") {
        Ok(native)
    } else {
        Err(format!(
            "URL local no valida para gestionar modelos: {openai_base}"
        ))
    }
}

pub fn list_models(base: &str) -> Result<Vec<InstalledModel>, String> {
    let url = format!("{base}/api/tags");
    let response: TagsResponse = ureq::get(&url)
        .call()
        .map_err(http_error)?
        .into_json()
        .map_err(|err| format!("No se pudo leer /api/tags: {err}"))?;
    let mut models: Vec<InstalledModel> = response
        .models
        .into_iter()
        .map(|entry| InstalledModel {
            name: entry.name,
            size_bytes: entry.size,
            modified_at: entry.modified_at,
        })
        .collect();
    models.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(models)
}

pub fn delete_model(base: &str, model: &str) -> Result<String, String> {
    let url = format!("{base}/api/delete");
    ureq::post(&url)
        .send_json(json!({ "name": model }))
        .map_err(http_error)?;
    Ok(format!("Modelo '{model}' borrado."))
}

pub fn pull_model(base: &str, model: &str, tx: &Sender<ModelEvent>) -> Result<String, String> {
    let url = format!("{base}/api/pull");
    let response = ureq::post(&url)
        .send_json(json!({ "name": model, "stream": true }))
        .map_err(http_error)?;

    let reader = BufReader::new(response.into_reader());
    let mut last_status = String::from("Solicitud enviada.");
    for line in reader.lines() {
        let line = line.map_err(|err| format!("Error leyendo progreso de descarga: {err}"))?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let update: PullLine = serde_json::from_str(trimmed)
            .map_err(|err| format!("Respuesta invalida del backend local: {err}"))?;
        if let Some(error) = update.error {
            return Err(format!("Error descargando '{model}': {error}"));
        }
        if let Some((status, is_progress)) = render_pull_status(&update) {
            last_status = status.clone();
            let event = if is_progress {
                ModelEvent::Progress(status)
            } else {
                ModelEvent::Status(status)
            };
            let _ = tx.send(event);
        }
    }
    Ok(format!("Modelo '{model}' listo. {last_status}"))
}

fn render_pull_status(update: &PullLine) -> Option<(String, bool)> {
    let mut status = update.status.clone().unwrap_or_default();
    if let (Some(completed), Some(total)) = (update.completed, update.total) {
        if total > 0 {
            let pct = (completed as f64 / total as f64) * 100.0;
            if status.is_empty() {
                status = "descargando".into();
            }
            return Some((
                format!("{status} {pct:.0}% ({}/{})", human_bytes(completed), human_bytes(total)),
                true,
            ));
        }
    }
    if status.is_empty() {
        None
    } else {
        Some((status, false))
    }
}

fn human_bytes(bytes: u64) -> String {
    const UNITS: [&str; 5] = ["B", "KB", "MB", "GB", "TB"];
    let mut value = bytes as f64;
    let mut unit = 0usize;
    while value >= 1024.0 && unit + 1 < UNITS.len() {
        value /= 1024.0;
        unit += 1;
    }
    if unit == 0 {
        format!("{} {}", bytes, UNITS[unit])
    } else {
        format!("{value:.1} {}", UNITS[unit])
    }
}

fn http_error(err: ureq::Error) -> String {
    match err {
        ureq::Error::Status(code, response) => {
            let url = response.get_url().to_string();
            let hint = if code == 404 {
                "Ese backend no expone la API nativa de Ollama para gestionar modelos."
            } else {
                "La operacion contra el backend local fallo."
            };
            format!("{hint} [{code}] {url}")
        }
        ureq::Error::Transport(err) => format!("No se pudo conectar con el backend local: {err}"),
    }
}

#[cfg(test)]
mod tests {
    use super::native_api_base;

    #[test]
    fn trims_openai_suffix_for_ollama_management() {
        assert_eq!(
            native_api_base("http://localhost:11434/v1").unwrap(),
            "http://localhost:11434"
        );
    }

    #[test]
    fn keeps_base_without_v1() {
        assert_eq!(
            native_api_base("http://localhost:11434").unwrap(),
            "http://localhost:11434"
        );
    }
}
