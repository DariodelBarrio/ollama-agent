//! Ratatui rendering for the launcher.

use ratatui::{
    layout::{Constraint, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{
        Block, BorderType, Borders, Clear, List, ListItem, Paragraph, Scrollbar,
        ScrollbarOrientation, ScrollbarState, Wrap,
    },
    Frame,
};

use crate::app::{
    App, FieldKind, Screen, MENU_HYBRID, MENU_LOCAL, MENU_MODELS, MENU_PROFILES, MENU_QUIT,
};
use crate::config::Variant;

const C_TITLE: Color = Color::Rgb(91, 155, 213);
const C_BORDER: Color = Color::Rgb(55, 55, 55);
const C_SELECT: Color = Color::Rgb(70, 130, 180);
const C_LOCAL: Color = Color::Rgb(80, 200, 120);
const C_HYBRID: Color = Color::Rgb(255, 174, 66);
const C_WARN: Color = Color::Rgb(255, 210, 90);
const C_OK: Color = Color::Green;
const C_ERR: Color = Color::Red;
const C_DIM: Color = Color::Rgb(110, 118, 129);
const BG: Color = Color::Rgb(18, 18, 18);

pub fn render(app: &App, frame: &mut Frame) {
    let area = frame.area();
    frame.render_widget(Block::default().style(Style::default().bg(BG)), area);

    let [header, body, statusbar] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(0),
        Constraint::Length(2),
    ])
    .areas(area);

    render_header(app, frame, header);
    render_statusbar(app, frame, statusbar);

    match app.screen {
        Screen::MainMenu => render_main_menu(app, frame, body),
        Screen::Configure => render_configure(app, frame, body),
        Screen::Models => render_models(app, frame, body),
        Screen::Profiles => render_profiles(app, frame, body),
        Screen::Session => render_session(app, frame, body),
    }
}

fn render_header(app: &App, frame: &mut Frame, area: Rect) {
    let variant_span = match app.profile.variant {
        Variant::Local => Span::styled(
            " Local ",
            Style::default().fg(C_LOCAL).add_modifier(Modifier::BOLD),
        ),
        Variant::Hybrid => Span::styled(
            " Hybrid ",
            Style::default().fg(C_HYBRID).add_modifier(Modifier::BOLD),
        ),
    };
    let screen = match app.screen {
        Screen::MainMenu => "launcher",
        Screen::Configure => "configure",
        Screen::Models => "models",
        Screen::Profiles => "profiles",
        Screen::Session => "session",
    };
    let line = Line::from(vec![
        Span::styled(
            "ollama-agent",
            Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD),
        ),
        Span::styled(" tui  ", Style::default().fg(C_DIM)),
        variant_span,
        Span::styled(
            format!("  {}  ", app.profile.model),
            Style::default().fg(C_DIM),
        ),
        Span::styled(screen, Style::default().fg(C_DIM)),
    ]);
    frame.render_widget(
        Paragraph::new(line).block(
            Block::default()
                .borders(Borders::BOTTOM)
                .border_style(Style::default().fg(C_BORDER)),
        ),
        area,
    );
}

fn render_statusbar(app: &App, frame: &mut Frame, area: Rect) {
    let (text, color) = if let Some((msg, is_err)) = &app.status {
        (msg.as_str(), if *is_err { C_ERR } else { C_OK })
    } else {
        (app.current_screen_hint(), C_DIM)
    };
    frame.render_widget(
        Paragraph::new(Span::styled(text, Style::default().fg(color))).block(
            Block::default()
                .borders(Borders::TOP)
                .border_style(Style::default().fg(C_BORDER)),
        ),
        area,
    );
}

fn render_main_menu(app: &App, frame: &mut Frame, area: Rect) {
    let popup = centered(46, 16, area);
    frame.render_widget(Clear, popup);

    let items: &[(usize, &str, Color)] = &[
        (MENU_LOCAL, "  Local session      ", C_LOCAL),
        (MENU_HYBRID, "  Hybrid session     ", C_HYBRID),
        (MENU_MODELS, "  Local models       ", C_WARN),
        (MENU_PROFILES, "  Profiles           ", C_TITLE),
        (MENU_QUIT, "  Quit               ", C_DIM),
    ];

    let list_items: Vec<ListItem> = items
        .iter()
        .map(|(idx, label, color)| {
            let selected = app.menu_idx == *idx;
            let style = if selected {
                Style::default()
                    .fg(BG)
                    .bg(*color)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(*color)
            };
            ListItem::new(Line::from(Span::styled(*label, style)))
        })
        .collect();

    let block = Block::default()
        .title(Span::styled(
            " Ollama Agent TUI ",
            Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(C_BORDER));

    frame.render_widget(List::new(list_items).block(block), popup);
}

fn render_configure(app: &App, frame: &mut Frame, area: Rect) {
    let block = Block::default()
        .title(Span::styled(
            format!(" Configure: {} ", app.profile.variant.label()),
            Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(C_BORDER));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    let [fields_area, preview_area] = Layout::vertical([Constraint::Min(0), Constraint::Length(9)])
        .margin(1)
        .areas(inner);

    let row_height = 2;
    let visible = (fields_area.height / row_height).max(1) as usize;
    let start = if app.field_idx >= visible {
        app.field_idx + 1 - visible
    } else {
        0
    };
    let end = (start + visible).min(app.fields.len());
    let constraints: Vec<Constraint> = (start..end)
        .map(|_| Constraint::Length(row_height))
        .collect();
    let rows = Layout::vertical(constraints).split(fields_area);

    for (i, (field, row)) in app.fields[start..end].iter().zip(rows.iter()).enumerate() {
        let idx = start + i;
        let focused = idx == app.field_idx;
        let label_style = if focused {
            Style::default().fg(C_SELECT).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::White)
        };
        let value = if field.editing {
            format!("{}|", field.value)
        } else if field.label == "API key cloud" && !field.value.is_empty() {
            format!("{}{}", "*".repeat(field.value.len().min(8)), " (guardada)")
        } else {
            field.value.clone()
        };
        let value_style = if field.editing {
            Style::default().fg(Color::Black).bg(Color::White)
        } else if focused {
            Style::default().fg(C_SELECT)
        } else {
            Style::default().fg(C_DIM)
        };
        let kind = match &field.kind {
            FieldKind::Bool => {
                if field.value == "on" {
                    "[x]"
                } else {
                    "[ ]"
                }
            }
            FieldKind::Select(_) => "[+]",
            FieldKind::Path => "[path]",
            FieldKind::Integer => "[int]",
            FieldKind::Float => "[float]",
            FieldKind::Text => "",
        };
        let line = Line::from(vec![
            Span::styled(format!("{:<18}", field.label), label_style),
            Span::styled(value, value_style),
            Span::styled(format!(" {kind}"), Style::default().fg(C_DIM)),
        ]);
        frame.render_widget(Paragraph::new(line), *row);
    }

    let preflight = app
        .preflight_report
        .as_ref()
        .map(|report| report.detail_lines().join("\n"))
        .unwrap_or_else(|| "preflight: pulsa F8 para validar backend y sandbox".into());
    let preview = Paragraph::new(format!(
        "{}\n{}\ncmd: {}",
        app.configure_preview_detail, preflight, app.configure_preview_command
    ))
    .wrap(Wrap { trim: false })
    .block(
        Block::default()
            .title(" Launch Preview ")
            .borders(Borders::TOP)
            .border_style(Style::default().fg(C_BORDER)),
    );
    frame.render_widget(preview, preview_area);
}

fn render_models(app: &App, frame: &mut Frame, area: Rect) {
    let block = Block::default()
        .title(Span::styled(
            " Local Models ",
            Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(C_BORDER));
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let [meta_area, content_area, input_area] = Layout::vertical([
        Constraint::Length(4),
        Constraint::Min(8),
        Constraint::Length(3),
    ])
    .margin(1)
    .areas(inner);

    let endpoint = match app.local_models_endpoint() {
        Ok(endpoint) => endpoint,
        Err(err) => err,
    };
    let meta = Paragraph::new(format!(
        "endpoint: {endpoint}\nperfil: {} · modelo activo: {}\n{}\nnota: requiere backend local compatible con la API nativa de Ollama",
        app.profile.name,
        app.profile.model,
        app.gpu_recommendation_summary(),
    ))
    .wrap(Wrap { trim: false })
    .block(Block::default().title(" Backend ").borders(Borders::ALL).border_style(Style::default().fg(C_BORDER)));
    frame.render_widget(meta, meta_area);

    let [models_area, logs_area] =
        Layout::horizontal([Constraint::Percentage(55), Constraint::Percentage(45)])
            .areas(content_area);

    let model_items: Vec<ListItem> = if app.models.is_empty() {
        vec![ListItem::new(Span::styled(
            "  (sin modelos listados)",
            Style::default().fg(C_DIM),
        ))]
    } else {
        app.models
            .iter()
            .enumerate()
            .map(|(idx, model)| {
                let selected = idx == app.model_idx;
                let size = model
                    .size_bytes
                    .map(human_bytes)
                    .unwrap_or_else(|| "?".into());
                let stamp = model.modified_at.as_deref().unwrap_or("sin fecha");
                let style = if selected {
                    Style::default()
                        .fg(BG)
                        .bg(C_SELECT)
                        .add_modifier(Modifier::BOLD)
                } else if model.name == app.profile.model {
                    Style::default().fg(C_LOCAL).add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(Color::White)
                };
                ListItem::new(Line::from(vec![
                    Span::styled(format!("{:<28}", model.name), style),
                    Span::styled(format!(" {size} "), Style::default().fg(C_DIM)),
                    Span::styled(stamp.to_string(), Style::default().fg(C_DIM)),
                ]))
            })
            .collect()
    };
    let models_block = Block::default()
        .title(" Installed ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(C_BORDER));
    frame.render_widget(List::new(model_items).block(models_block), models_area);

    let logs_block = Block::default()
        .title(if app.model_task_running {
            " Model Activity "
        } else {
            " Model Log "
        })
        .borders(Borders::ALL)
        .border_style(Style::default().fg(C_BORDER));
    let visible_log_height = logs_area.height.saturating_sub(2);
    frame.render_widget(
        Paragraph::new(app.model_window_text(visible_log_height))
            .wrap(Wrap { trim: false })
            .block(logs_block),
        logs_area,
    );

    let input_style = if app.model_input_editing {
        Style::default().fg(Color::Black).bg(Color::White)
    } else {
        Style::default().fg(C_DIM)
    };
    let input_text = if app.model_input_editing {
        format!("{}_", app.model_input_buffer)
    } else if app.model_input_buffer.is_empty() {
        "Pulsa g para descargar el recomendado por GPU, o p para escribir uno manualmente.".into()
    } else {
        app.model_input_buffer.clone()
    };
    let input = Paragraph::new(Span::styled(input_text, input_style)).block(
        Block::default()
            .title(" Pull Model ")
            .borders(Borders::ALL)
            .border_style(Style::default().fg(C_BORDER)),
    );
    frame.render_widget(input, input_area);
}

fn render_profiles(app: &App, frame: &mut Frame, area: Rect) {
    let popup = centered(72, 80, area);
    frame.render_widget(Clear, popup);

    let items: Vec<ListItem> = if app.store.profiles.is_empty() {
        vec![ListItem::new(Span::styled(
            "  (sin perfiles guardados)",
            Style::default().fg(C_DIM),
        ))]
    } else {
        app.store
            .profiles
            .iter()
            .enumerate()
            .map(|(i, p)| {
                let selected = i == app.profile_idx;
                let style = if selected {
                    Style::default()
                        .fg(BG)
                        .bg(C_SELECT)
                        .add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(Color::White)
                };
                let variant_color = if p.variant == Variant::Local {
                    C_LOCAL
                } else {
                    C_HYBRID
                };
                ListItem::new(Line::from(vec![
                    Span::styled(format!("{:<16}", p.name), style),
                    Span::styled(
                        format!(" {} ", p.variant.label()),
                        Style::default().fg(variant_color),
                    ),
                    Span::styled(format!(" {}", p.model), Style::default().fg(C_DIM)),
                ]))
            })
            .collect()
    };

    let block = Block::default()
        .title(Span::styled(
            " Profiles ",
            Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(C_BORDER));

    frame.render_widget(List::new(items).block(block), popup);
}

fn render_session(app: &App, frame: &mut Frame, area: Rect) {
    let [meta_area, log_area, input_area] = Layout::vertical([
        Constraint::Length(4),
        Constraint::Min(4),
        Constraint::Length(3),
    ])
    .areas(area);

    let meta = Paragraph::new(format!(
        "{}\nEnter enviar · F6 stop · Esc return to config",
        app.session_meta_text(),
    ))
    .wrap(Wrap { trim: false })
    .block(
        Block::default()
            .title(" Session ")
            .borders(Borders::ALL)
            .border_style(Style::default().fg(C_BORDER)),
    );
    frame.render_widget(meta, meta_area);

    let [tool_area, output_area] = if log_area.width >= 96 {
        Layout::horizontal([Constraint::Percentage(34), Constraint::Percentage(66)]).areas(log_area)
    } else {
        Layout::horizontal([Constraint::Percentage(0), Constraint::Percentage(100)]).areas(log_area)
    };
    if log_area.width >= 96 {
        let visible_tool_height = tool_area.height.saturating_sub(2);
        let tools = Paragraph::new(app.recent_tools_text(visible_tool_height))
            .wrap(Wrap { trim: false })
            .block(
                Block::default()
                    .title(" Recent Actions ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(C_BORDER)),
            );
        frame.render_widget(tools, tool_area);
    }

    let visible_log_height = output_area.height.saturating_sub(2);
    let log = Paragraph::new(app.session_window_text(visible_log_height))
        .wrap(Wrap { trim: false })
        .block(
            Block::default()
                .title(app.session_view_label())
                .borders(Borders::ALL)
                .border_style(Style::default().fg(C_BORDER)),
        );
    frame.render_widget(log, output_area);
    if let Some((total, position, viewport)) = app.session_scrollbar_metrics(visible_log_height) {
        let mut scrollbar_state = ScrollbarState::new(total)
            .position(position)
            .viewport_content_length(viewport);
        let scrollbar = Scrollbar::new(ScrollbarOrientation::VerticalRight)
            .track_symbol(Some("│"))
            .thumb_symbol("█")
            .begin_symbol(None)
            .end_symbol(None)
            .style(Style::default().fg(Color::Rgb(65, 65, 65)))
            .thumb_style(Style::default().fg(Color::Rgb(190, 190, 190)));
        frame.render_stateful_widget(scrollbar, output_area, &mut scrollbar_state);
    }

    let input_style = Style::default().fg(Color::Black).bg(Color::White);
    let input_text = if app.input_buffer.is_empty() {
        "|".into()
    } else {
        let mut text = app.input_buffer.clone();
        let cursor = app.input_cursor.min(text.len());
        text.insert(cursor, '|');
        text
    };
    let input = Paragraph::new(Span::styled(input_text, input_style)).block(
        Block::default()
            .title(if app.session_mouse_mode {
                " Input · mouse on "
            } else {
                " Input · mouse off "
            })
            .borders(Borders::ALL)
            .border_style(Style::default().fg(C_BORDER)),
    );
    frame.render_widget(input, input_area);
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

fn centered(w: u16, h: u16, area: Rect) -> Rect {
    let w = w.min(area.width);
    let h = h.min(area.height);
    let x = area.x + (area.width.saturating_sub(w)) / 2;
    let y = area.y + (area.height.saturating_sub(h)) / 2;
    Rect {
        x,
        y,
        width: w,
        height: h,
    }
}
