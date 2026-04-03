//! Ratatui rendering — pure functions, no state mutation.

use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, Clear, List, ListItem, Paragraph},
};

use crate::app::{App, FieldKind, Screen, MENU_HYBRID, MENU_LOCAL, MENU_PROFILES, MENU_QUIT};
use crate::config::Variant;

// ── Palette ───────────────────────────────────────────────────────────────────

const C_TITLE:  Color = Color::Rgb(91, 155, 213);
const C_BORDER: Color = Color::Rgb(55, 55, 55);
const C_SELECT: Color = Color::Rgb(0, 120, 215);
const C_LOCAL:  Color = Color::Rgb(80, 200, 120);
const C_HYBRID: Color = Color::Rgb(180, 140, 240);
const C_OK:     Color = Color::Green;
const C_ERR:    Color = Color::Red;
const C_DIM:    Color = Color::Rgb(90, 90, 90);
const BG:       Color = Color::Rgb(18, 18, 18);

// ── Entry point ───────────────────────────────────────────────────────────────

pub fn render(app: &App, frame: &mut Frame) {
    let area = frame.area();

    // Dark background fill
    frame.render_widget(
        Block::default().style(Style::default().bg(BG)),
        area,
    );

    let [header, body, statusbar] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(0),
        Constraint::Length(2),
    ])
    .areas(area);

    render_header(app, frame, header);
    render_statusbar(app, frame, statusbar);

    match app.screen {
        Screen::MainMenu  => render_main_menu(app, frame, body),
        Screen::Configure => render_configure(app, frame, body),
        Screen::Profiles  => render_profiles(app, frame, body),
    }
}

// ── Header ────────────────────────────────────────────────────────────────────

fn render_header(app: &App, frame: &mut Frame, area: Rect) {
    let variant_span = match app.profile.variant {
        Variant::Local  => Span::styled(" Local ",  Style::default().fg(C_LOCAL).add_modifier(Modifier::BOLD)),
        Variant::Hybrid => Span::styled(" Hybrid ", Style::default().fg(C_HYBRID).add_modifier(Modifier::BOLD)),
    };
    let line = Line::from(vec![
        Span::styled("ollama-agent", Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD)),
        Span::styled(" tui  ", Style::default().fg(C_DIM)),
        variant_span,
        Span::styled(format!("  {}", app.profile.model), Style::default().fg(C_DIM)),
    ]);
    frame.render_widget(
        Paragraph::new(line)
            .block(Block::default().borders(Borders::BOTTOM).border_style(Style::default().fg(C_BORDER))),
        area,
    );
}

// ── Status bar ────────────────────────────────────────────────────────────────

fn render_statusbar(app: &App, frame: &mut Frame, area: Rect) {
    let (text, color) = if let Some((msg, is_err)) = &app.status {
        (msg.as_str(), if *is_err { C_ERR } else { C_OK })
    } else {
        let hint = match app.screen {
            Screen::MainMenu  => "j/k  navegar    Enter  seleccionar    q  salir",
            Screen::Configure => "Tab  campo    Enter  editar    F5  lanzar    F2  guardar    Esc  volver",
            Screen::Profiles  => "j/k  navegar    Enter  cargar    d  eliminar    Esc  volver",
        };
        (hint, C_DIM)
    };
    frame.render_widget(
        Paragraph::new(Span::styled(text, Style::default().fg(color)))
            .block(Block::default().borders(Borders::TOP).border_style(Style::default().fg(C_BORDER))),
        area,
    );
}

// ── Main menu ─────────────────────────────────────────────────────────────────

fn render_main_menu(app: &App, frame: &mut Frame, area: Rect) {
    let popup = centered(44, 14, area);
    frame.render_widget(Clear, popup);

    let items: &[(usize, &str, Color)] = &[
        (MENU_LOCAL,    "  Launch Local Agent   ", C_LOCAL),
        (MENU_HYBRID,   "  Launch Hybrid Agent  ", C_HYBRID),
        (MENU_PROFILES, "  Manage Profiles      ", C_TITLE),
        (MENU_QUIT,     "  Quit                 ", C_DIM),
    ];

    let list_items: Vec<ListItem> = items
        .iter()
        .map(|(idx, label, color)| {
            let selected = app.menu_idx == *idx;
            let style = if selected {
                Style::default().fg(BG).bg(*color).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(*color)
            };
            ListItem::new(Line::from(Span::styled(*label, style)))
        })
        .collect();

    let block = Block::default()
        .title(Span::styled(
            " Ollama Agent Launcher ",
            Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(C_BORDER))
        .style(Style::default().bg(BG));

    frame.render_widget(List::new(list_items).block(block), popup);
}

// ── Configure ─────────────────────────────────────────────────────────────────

fn render_configure(app: &App, frame: &mut Frame, area: Rect) {
    let title = format!(" Configure: {} Agent ", app.profile.variant.label());
    let block = Block::default()
        .title(Span::styled(title, Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD)))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(C_BORDER))
        .style(Style::default().bg(BG));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if app.fields.is_empty() {
        return;
    }

    // Pad inside the block
    let [fields_area, preview_area] = Layout::vertical([
        Constraint::Min(0),
        Constraint::Length(3),
    ])
    .margin(1)
    .areas(inner);

    // One row per field, with a blank row between them via Length(2)
    let n         = app.fields.len();
    let row_h     = 2u16;
    let max_fit   = (fields_area.height / row_h) as usize;
    let visible_n = n.min(max_fit);

    // Scroll so the selected field is always visible
    let start = if app.field_idx >= visible_n {
        app.field_idx + 1 - visible_n
    } else {
        0
    };
    let end = (start + visible_n).min(n);

    let constraints: Vec<Constraint> =
        (start..end).map(|_| Constraint::Length(row_h)).collect();
    let rows = Layout::vertical(constraints).split(fields_area);

    for (i, (field, row)) in app.fields[start..end].iter().zip(rows.iter()).enumerate() {
        let abs_idx = start + i;
        let focused = abs_idx == app.field_idx;

        let label_style = if focused {
            Style::default().fg(C_SELECT).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::White)
        };

        // Value display with inline cursor when editing
        let value_display: String = if field.editing {
            format!("{}_", field.value)
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

        // Small type indicator
        let indicator = match &field.kind {
            FieldKind::Bool          => if field.value == "on" { "[x]" } else { "[ ]" },
            FieldKind::Select(_)     => "[+]",
            _ => "   ",
        };

        let line = Line::from(vec![
            Span::styled(format!("{:<22}", field.label), label_style),
            Span::styled(&value_display, value_style),
            Span::styled(format!(" {}", indicator), Style::default().fg(C_DIM)),
        ]);

        frame.render_widget(Paragraph::new(line), *row);
    }

    // Command preview strip
    let preview_text = crate::agent::command_preview(&app.profile, &app.repo_root);
    let preview = Paragraph::new(
        Line::from(vec![
            Span::styled("cmd: ", Style::default().fg(C_DIM)),
            Span::styled(
                // truncate so it fits in one line
                if preview_text.len() > preview_area.width.saturating_sub(6) as usize {
                    format!("{}...", &preview_text[..(preview_area.width.saturating_sub(9)) as usize])
                } else {
                    preview_text
                },
                Style::default().fg(Color::Rgb(60, 60, 60)),
            ),
        ])
    )
    .block(Block::default().borders(Borders::TOP).border_style(Style::default().fg(C_BORDER)));

    frame.render_widget(preview, preview_area);
}

// ── Profiles ──────────────────────────────────────────────────────────────────

fn render_profiles(app: &App, frame: &mut Frame, area: Rect) {
    let popup = centered(70, 80, area);
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
                let sel    = i == app.profile_idx;
                let prefix = if sel { " > " } else { "   " };
                let (vlabel, vcolor) = match p.variant {
                    Variant::Local  => ("Local ", C_LOCAL),
                    Variant::Hybrid => ("Hybrid", C_HYBRID),
                };
                let name_style = if sel {
                    Style::default().fg(BG).bg(C_SELECT).add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(Color::White)
                };
                ListItem::new(Line::from(vec![
                    Span::styled(prefix, Style::default().fg(C_SELECT)),
                    Span::styled(&p.name, name_style),
                    Span::styled("  ", Style::default()),
                    Span::styled(vlabel, Style::default().fg(vcolor)),
                    Span::styled(format!("  {}", p.model), Style::default().fg(C_DIM)),
                ]))
            })
            .collect()
    };

    let block = Block::default()
        .title(Span::styled(" Perfiles ", Style::default().fg(C_TITLE).add_modifier(Modifier::BOLD)))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(C_BORDER))
        .style(Style::default().bg(BG));

    frame.render_widget(List::new(items).block(block), popup);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/// Returns a centered Rect with absolute width/height (in cells).
fn centered(w: u16, h: u16, area: Rect) -> Rect {
    let w = w.min(area.width);
    let h = h.min(area.height);
    let x = area.x + (area.width.saturating_sub(w)) / 2;
    let y = area.y + (area.height.saturating_sub(h)) / 2;
    Rect { x, y, width: w, height: h }
}
