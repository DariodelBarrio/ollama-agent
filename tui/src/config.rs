//! Profile types and TOML persistence.
//!
//! Profiles are stored in the OS config directory:
//!   Linux/macOS: ~/.config/ollama-agent/profiles.toml
//!   Windows:     %APPDATA%\ollama-agent\profiles.toml

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Variant {
    #[default]
    Local,
    Hybrid,
}

impl Variant {
    pub fn label(&self) -> &'static str {
        match self {
            Variant::Local => "Local",
            Variant::Hybrid => "Hybrid",
        }
    }
}

/// All parameters needed to launch an agent session.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Profile {
    pub name: String,
    pub variant: Variant,
    pub model: String,
    pub work_dir: String,
    pub tag: String,
    pub ctx: u32,
    pub temperature: f32,
    pub system_prompt: String,
    // Local-specific
    pub api_base: String,
    // Hybrid-specific
    pub backend: String,
    pub critic: bool,
    pub groq_model: String,
    pub local_url: String,
    pub sandbox: String,
    pub sandbox_image: String,
}

impl Default for Profile {
    fn default() -> Self {
        Self {
            name: "default".into(),
            variant: Variant::Local,
            model: "qwen2.5-coder:14b".into(),
            work_dir: ".".into(),
            tag: "AGENTE".into(),
            ctx: 16384,
            temperature: 0.15,
            system_prompt: String::new(),
            api_base: "http://localhost:11434/v1".into(),
            backend: "auto".into(),
            critic: false,
            groq_model: "llama-3.3-70b-versatile".into(),
            local_url: "http://localhost:11434/v1".into(),
            sandbox: String::new(),
            sandbox_image: "python:3.12-slim".into(),
        }
    }
}

impl Profile {
    pub fn local_management_base(&self) -> &str {
        match self.variant {
            Variant::Local => &self.api_base,
            Variant::Hybrid => &self.local_url,
        }
    }
}

#[derive(Debug, Default, Serialize, Deserialize)]
pub struct ProfileStore {
    #[serde(default)]
    pub profiles: Vec<Profile>,
}

impl ProfileStore {
    pub fn path() -> PathBuf {
        dirs::config_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("ollama-agent")
            .join("profiles.toml")
    }

    pub fn load() -> Self {
        let path = Self::path();
        let content = std::fs::read_to_string(&path).unwrap_or_default();
        toml::from_str(&content).unwrap_or_default()
    }

    pub fn save(&self) -> Result<(), String> {
        let path = Self::path();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let content = toml::to_string_pretty(self).map_err(|e| e.to_string())?;
        std::fs::write(&path, content).map_err(|e| e.to_string())
    }

    pub fn upsert(&mut self, profile: Profile) {
        match self.profiles.iter().position(|p| p.name == profile.name) {
            Some(idx) => self.profiles[idx] = profile,
            None => self.profiles.push(profile),
        }
    }

    pub fn remove(&mut self, name: &str) {
        self.profiles.retain(|p| p.name != name);
    }
}
