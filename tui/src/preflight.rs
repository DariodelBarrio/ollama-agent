//! Lightweight launcher preflight checks.

use crate::config::{Profile, Variant};
use std::process::Command;
use std::time::Duration;

const HTTP_TIMEOUT_MS: u64 = 1200;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CheckStatus {
    Ok,
    Warning,
    Failed,
}

impl CheckStatus {
    pub fn label(&self) -> &'static str {
        match self {
            CheckStatus::Ok => "ok",
            CheckStatus::Warning => "warn",
            CheckStatus::Failed => "fail",
        }
    }
}

#[derive(Debug, Clone)]
pub struct CheckResult {
    pub name: &'static str,
    pub status: CheckStatus,
    pub summary: String,
}

#[derive(Debug, Clone, Default)]
pub struct PreflightReport {
    pub checks: Vec<CheckResult>,
}

impl PreflightReport {
    pub fn has_blockers(&self) -> bool {
        self.checks
            .iter()
            .any(|check| check.status == CheckStatus::Failed)
    }

    pub fn summary_line(&self) -> String {
        if self.checks.is_empty() {
            return "preflight: sin ejecutar".into();
        }
        self.checks
            .iter()
            .map(|check| format!("{}={} ", check.name, check.status.label()))
            .collect::<String>()
            .trim()
            .to_string()
    }

    pub fn detail_lines(&self) -> Vec<String> {
        self.checks
            .iter()
            .map(|check| {
                format!(
                    "[{}] {}: {}",
                    check.status.label(),
                    check.name,
                    check.summary
                )
            })
            .collect()
    }
}

pub fn run(profile: &Profile) -> PreflightReport {
    let mut report = PreflightReport::default();
    match profile.variant {
        Variant::Local => {
            report
                .checks
                .push(check_backend("local", &profile.api_base, None, true));
        }
        Variant::Hybrid => {
            match profile.backend.as_str() {
                "local" | "auto" | "" => {
                    report.checks.push(check_backend(
                        "hybrid-local",
                        &profile.local_url,
                        None,
                        true,
                    ));
                }
                "groq" => {
                    report.checks.push(check_env(
                        "groq",
                        env_has_value("GROQ_API_KEY") || !profile.remote_api_key.trim().is_empty(),
                        "Falta GROQ_API_KEY para usar backend Groq.",
                    ));
                }
                "remote" => {
                    let api_key = remote_key_for_profile(profile);
                    report.checks.push(check_backend(
                        "remote",
                        &profile.remote_url,
                        api_key.as_deref(),
                        true,
                    ));
                }
                _ => {
                    report.checks.push(CheckResult {
                        name: "backend",
                        status: CheckStatus::Warning,
                        summary: format!(
                            "Backend '{}' no tiene preflight especÃ­fico.",
                            profile.backend
                        ),
                    });
                }
            }
            if !profile.sandbox.trim().is_empty() {
                report.checks.push(check_sandbox(profile));
            }
        }
    }
    report
}

fn remote_key_for_profile(profile: &Profile) -> Option<String> {
    if !profile.remote_api_key.trim().is_empty() {
        return Some(profile.remote_api_key.clone());
    }
    let envs: &[&str] = match profile.cloud_provider.as_str() {
        "groq" => &["GROQ_API_KEY"],
        "openai" => &["OPENAI_API_KEY", "REMOTE_API_KEY"],
        "openrouter" => &["OPENROUTER_API_KEY", "REMOTE_API_KEY"],
        _ => &["REMOTE_API_KEY"],
    };
    envs.iter().find_map(|name| {
        std::env::var(name)
            .ok()
            .filter(|value| !value.trim().is_empty())
    })
}

fn env_has_value(name: &str) -> bool {
    std::env::var(name)
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false)
}

fn check_env(name: &'static str, ok: bool, failure: &str) -> CheckResult {
    if ok {
        CheckResult {
            name,
            status: CheckStatus::Ok,
            summary: "ConfiguraciÃ³n detectada.".into(),
        }
    } else {
        CheckResult {
            name,
            status: CheckStatus::Failed,
            summary: failure.into(),
        }
    }
}

fn check_backend(
    name: &'static str,
    base_url: &str,
    api_key: Option<&str>,
    required: bool,
) -> CheckResult {
    let trimmed = base_url.trim();
    if trimmed.is_empty() {
        return CheckResult {
            name,
            status: if required {
                CheckStatus::Failed
            } else {
                CheckStatus::Warning
            },
            summary: "URL vacÃ­a.".into(),
        };
    }
    if !trimmed.starts_with("http://") && !trimmed.starts_with("https://") {
        return CheckResult {
            name,
            status: CheckStatus::Failed,
            summary: format!("URL no vÃ¡lida: {trimmed}"),
        };
    }
    let url = models_url(trimmed);
    let agent = ureq::AgentBuilder::new()
        .timeout_read(Duration::from_millis(HTTP_TIMEOUT_MS))
        .timeout_write(Duration::from_millis(HTTP_TIMEOUT_MS))
        .timeout_connect(Duration::from_millis(HTTP_TIMEOUT_MS))
        .build();
    let mut request = agent.get(&url);
    if let Some(token) = api_key.filter(|value| !value.trim().is_empty()) {
        request = request.set("Authorization", &format!("Bearer {token}"));
    }
    match request.call() {
        Ok(response) => CheckResult {
            name,
            status: CheckStatus::Ok,
            summary: format!("{} respondiÃ³ con {}", url, response.status()),
        },
        Err(ureq::Error::Status(code, _)) => CheckResult {
            name,
            status: if code == 401 || code == 403 {
                CheckStatus::Failed
            } else {
                CheckStatus::Warning
            },
            summary: format!("{} respondiÃ³ con HTTP {}", url, code),
        },
        Err(err) => CheckResult {
            name,
            status: if required {
                CheckStatus::Failed
            } else {
                CheckStatus::Warning
            },
            summary: format!("No se pudo conectar a {}: {}", url, err),
        },
    }
}

fn check_sandbox(profile: &Profile) -> CheckResult {
    let docker = match Command::new("docker").arg("--version").output() {
        Ok(output) if output.status.success() => output,
        Ok(output) => {
            return CheckResult {
                name: "sandbox",
                status: CheckStatus::Failed,
                summary: format!(
                    "Docker no disponible: {}",
                    String::from_utf8_lossy(&output.stderr).trim()
                ),
            }
        }
        Err(err) => {
            return CheckResult {
                name: "sandbox",
                status: CheckStatus::Failed,
                summary: format!("No se pudo ejecutar docker: {err}"),
            }
        }
    };

    match Command::new("docker").args(["image", "inspect", &profile.sandbox_image]).output() {
        Ok(output) if output.status.success() => CheckResult {
            name: "sandbox",
            status: CheckStatus::Ok,
            summary: format!(
                "{} listo; imagen '{}' disponible.",
                String::from_utf8_lossy(&docker.stdout).trim(),
                profile.sandbox_image
            ),
        },
        Ok(_) => CheckResult {
            name: "sandbox",
            status: CheckStatus::Failed,
            summary: format!(
                "Docker responde, pero falta la imagen '{}'. PrepÃ¡rala antes de lanzar la sesiÃ³n.",
                profile.sandbox_image
            ),
        },
        Err(err) => CheckResult {
            name: "sandbox",
            status: CheckStatus::Failed,
            summary: format!("No se pudo inspeccionar la imagen Docker: {err}"),
        },
    }
}

fn models_url(base_url: &str) -> String {
    format!("{}/models", base_url.trim_end_matches('/'))
}

#[cfg(test)]
mod tests {
    use super::{models_url, PreflightReport};

    #[test]
    fn models_url_preserves_v1_shape() {
        assert_eq!(
            models_url("http://localhost:11434/v1"),
            "http://localhost:11434/v1/models"
        );
    }

    #[test]
    fn summary_without_checks_is_clear() {
        assert_eq!(
            PreflightReport::default().summary_line(),
            "preflight: sin ejecutar"
        );
    }
}
