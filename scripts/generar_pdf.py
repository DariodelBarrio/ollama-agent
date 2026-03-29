"""
Genera la documentacion del proyecto como PDF — diseno moderno.
"""
from fpdf import FPDF
from fpdf.enums import XPos, YPos, RenderStyle
import math, os

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "documentacion_agente_local.pdf")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
FONT_DIR = r"C:\Windows\Fonts"

# Paleta
AZUL      = (30,  90, 160)
AZUL_LT   = (70, 130, 200)
AZUL_PLT  = (220, 235, 255)
GRIS_BG   = (248, 249, 252)
GRIS_MED  = (180, 190, 210)
NEGRO     = (30,  30,  38)
BLANCO    = (255, 255, 255)
VERDE     = (34, 153,  74)
VERDE_PLT = (220, 245, 228)
NARANJA   = (200,  90,  20)
NRNJ_PLT  = (255, 237, 220)
CODE_BG   = (22,  27,  40)
CODE_FG   = (190, 215, 255)
ACNT      = (100, 180, 255)
ROJO      = (180,  40,  40)


class PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("R",  "",  os.path.join(FONT_DIR, "arial.ttf"))
        self.add_font("R",  "B", os.path.join(FONT_DIR, "arialbd.ttf"))
        self.add_font("R",  "I", os.path.join(FONT_DIR, "ariali.ttf"))
        self.add_font("Mono","", os.path.join(FONT_DIR, "cour.ttf"))
        self.set_margins(22, 22, 22)
        self.set_auto_page_break(auto=True, margin=22)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_fill_color(*AZUL)
        self.rect(0, 0, 140, 8, "F")
        self.set_fill_color(*AZUL_LT)
        self.rect(140, 0, 50, 8, "F")
        self.set_fill_color(180, 210, 240)
        self.rect(190, 0, 20, 8, "F")
        self.set_font("R", "B", 7)
        self.set_text_color(*BLANCO)
        self.set_xy(8, 1)
        self.cell(0, 6, "Agente de Programacion Local  |  Ollama + Python + RTX 5070")
        self.set_text_color(*NEGRO)
        self.ln(10)

    def footer(self):
        self.set_y(-13)
        self.set_draw_color(*AZUL_LT)
        self.set_line_width(0.5)
        self.line(22, self.get_y(), 188, self.get_y())
        self.set_font("R", "", 7.5)
        self.set_text_color(*GRIS_MED)
        self.set_y(self.get_y() + 1)
        self.cell(0, 5, f"{self.page_no()}", align="C")

    def _circle(self, cx, cy, r, fill=None, stroke=None):
        if fill:
            self.set_fill_color(*fill)
        if stroke:
            self.set_draw_color(*stroke)
        style = "FD" if fill and stroke else ("F" if fill else "D")
        self.ellipse(cx - r, cy - r, r * 2, r * 2, style)

    def _rounded(self, x, y, w, h, r, fill=None, stroke=None):
        self.set_line_width(0.3)
        if fill:
            self.set_fill_color(*fill)
        if stroke:
            self.set_draw_color(*stroke)
        if fill and stroke:
            style = RenderStyle.DF
        elif fill:
            style = RenderStyle.F
        else:
            style = RenderStyle.D
        self._draw_rounded_rect(x, y, w, h, style, True, r)

    def section_title(self, text, level=1):
        self.ln(5)
        y = self.get_y()
        if level == 1:
            self.set_fill_color(*AZUL)
            self.rect(22, y, 3.5, 10, "F")
            self.set_font("R", "B", 13)
            self.set_text_color(*NEGRO)
            self.set_xy(28, y + 1)
            self.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        elif level == 2:
            self.set_fill_color(*AZUL_LT)
            self.rect(22, y + 1, 2.5, 7, "F")
            self.set_font("R", "B", 10.5)
            self.set_text_color(*AZUL)
            self.set_xy(27, y)
            self.cell(0, 9, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        elif level == 3:
            self.set_font("R", "B", 9.5)
            self.set_text_color(*AZUL_LT)
            self.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*NEGRO)
        self.ln(1)

    def body(self, text, indent=0):
        self.set_font("R", "", 9.5)
        self.set_text_color(50, 50, 60)
        self.set_x(22 + indent)
        self.multi_cell(166 - indent, 5.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def bullet(self, items, color=AZUL):
        self.set_font("R", "", 9.5)
        self.set_text_color(50, 50, 60)
        for item in items:
            y = self.get_y() + 2.5
            self._circle(26, y, 1.5, fill=color)
            self.set_xy(30, self.get_y())
            self.multi_cell(158, 5.5, item, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def step_list(self, items):
        self.set_font("R", "", 9.5)
        self.set_text_color(50, 50, 60)
        for i, item in enumerate(items, 1):
            y = self.get_y()
            self._circle(27, y + 3, 4, fill=AZUL)
            self.set_font("R", "B", 8)
            self.set_text_color(*BLANCO)
            self.set_xy(23.5, y + 0.8)
            self.cell(7, 5, str(i), align="C")
            self.set_font("R", "", 9.5)
            self.set_text_color(50, 50, 60)
            self.set_xy(33, y)
            self.multi_cell(155, 5.5, item, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1)

    def code_block(self, code, lang=""):
        lines = code.strip().splitlines()
        h = len(lines) * 5.2 + 14
        y = self.get_y()
        if y + h > 268:
            self.add_page()
            y = self.get_y()
        self._rounded(22, y, 166, h, 3, fill=CODE_BG)
        for xi, col in enumerate([(220,90,80),(230,180,60),(80,185,90)]):
            self._circle(29 + xi * 8, y + 5, 2.2, fill=col)
        if lang:
            self.set_font("R", "I", 7)
            self.set_text_color(120, 160, 210)
            self.set_xy(55, y + 2)
            self.cell(0, 5, lang)
        self.set_font("Mono", "", 8)
        self.set_text_color(*CODE_FG)
        self.set_xy(26, y + 11)
        for line in lines:
            self.set_x(26)
            self.cell(0, 5.2, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(y + h + 3)
        self.set_text_color(*NEGRO)
        self.ln(1)

    def info_table(self, headers, rows, col_widths):
        y = self.get_y()
        total_w = sum(col_widths)
        self._rounded(22, y, total_w, 8, 2, fill=AZUL)
        self.set_font("R", "B", 8.5)
        self.set_text_color(*BLANCO)
        x = 22
        for i, h in enumerate(headers):
            self.set_xy(x + 2, y + 1)
            self.cell(col_widths[i] - 2, 6, h)
            x += col_widths[i]
        self.set_y(y + 8)
        for ri, row in enumerate(rows):
            ry = self.get_y()
            bg = AZUL_PLT if ri % 2 == 0 else BLANCO
            self.set_fill_color(*bg)
            self.rect(22, ry, total_w, 6.5, "F")
            self.set_font("R", "", 8.5)
            self.set_text_color(*NEGRO)
            x = 22
            for i, cell in enumerate(row):
                self.set_xy(x + 2, ry + 0.5)
                self.cell(col_widths[i] - 2, 5.5, cell)
                x += col_widths[i]
            self.set_y(ry + 6.5)
        self.set_draw_color(*AZUL_LT)
        self.set_line_width(0.3)
        self.line(22, self.get_y(), 22 + total_w, self.get_y())
        self.ln(4)

    def pill(self, label, fg, bg):
        self.set_font("R", "B", 8)
        w = self.get_string_width(label) + 8
        x, y = self.get_x(), self.get_y()
        self._rounded(x, y, w, 6, 3, fill=bg)
        self.set_text_color(*fg)
        self.set_xy(x, y)
        self.cell(w, 6, label, align="C")
        self.set_x(x + w + 3)
        self.set_text_color(*NEGRO)

    def tool_card(self, name, desc, note, accent=AZUL):
        y = self.get_y()
        if y + 22 > 268:
            self.add_page()
            y = self.get_y()
        self._rounded(22.8, y + 0.8, 165.4, 22, 2, fill=(235, 238, 245))
        self._rounded(22, y, 165, 22, 2, fill=GRIS_BG)
        self.set_fill_color(*accent)
        self.rect(22, y, 3, 22, "F")
        self.set_font("R", "B", 10)
        self.set_text_color(*accent)
        self.set_xy(28, y + 2)
        self.cell(0, 5.5, name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("R", "", 9)
        self.set_text_color(*NEGRO)
        self.set_x(28)
        self.multi_cell(157, 4.8, desc, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("R", "I", 8)
        self.set_text_color(120, 130, 150)
        self.set_x(28)
        self.multi_cell(157, 4.5, note, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(y + 22 + 2)
        self.set_text_color(*NEGRO)

    def model_card(self, tag, model, pill_label, pill_fg, pill_bg, desc, items, cmd):
        y = self.get_y()
        if y + 75 > 268:
            self.add_page()
            y = self.get_y()
        self._rounded(22.8, y + 0.8, 165.4, 70, 4, fill=(230, 235, 245))
        self._rounded(22, y, 165, 70, 4, fill=BLANCO)
        self._rounded(22, y, 165, 18, 4, fill=AZUL)
        self.set_fill_color(*AZUL)
        self.rect(22, y + 10, 165, 8, "F")
        self.set_font("R", "B", 14)
        self.set_text_color(*BLANCO)
        self.set_xy(28, y + 2)
        self.cell(30, 13, tag)
        self.set_font("R", "", 9)
        self.set_text_color(180, 215, 255)
        self.set_xy(60, y + 5)
        self.cell(0, 6, model)
        self.set_xy(130, y + 4)
        self.pill(pill_label, pill_fg, pill_bg)
        self.set_font("R", "", 9)
        self.set_text_color(60, 65, 80)
        self.set_xy(27, y + 21)
        self.multi_cell(157, 5, desc, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for item in items:
            cy = self.get_y() + 2.5
            self._circle(29, cy, 1.5, fill=AZUL_LT)
            self.set_xy(33, self.get_y())
            self.set_font("R", "", 8.5)
            self.set_text_color(50, 55, 70)
            self.cell(0, 5, item, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        cmd_y = y + 59
        self._rounded(27, cmd_y, 153, 8, 2, fill=CODE_BG)
        self.set_font("Mono", "", 7.5)
        self.set_text_color(*CODE_FG)
        self.set_xy(30, cmd_y + 1)
        self.cell(0, 6, cmd)
        self.set_y(y + 70 + 4)
        self.set_text_color(*NEGRO)


# ==============================================================================
#  PORTADA
# ==============================================================================
pdf = PDF()
pdf.add_page()

pdf.set_fill_color(12, 20, 40)
pdf.rect(0, 0, 210, 297, "F")

pdf._circle(170, 50, 55, fill=(20, 45, 90))
pdf._circle(30, 230, 70, fill=(15, 35, 75))
pdf._circle(105, 290, 40, fill=(25, 55, 110))

pts = [(0, 160), (210, 110), (210, 230), (0, 297)]
pdf.set_fill_color(20, 50, 100)
pdf.polygon(pts, style="F")

pdf._circle(105, 95, 38, fill=(25, 65, 135))
pdf._circle(105, 95, 30, fill=(35, 85, 165))
pdf._circle(105, 95, 22, fill=(50, 110, 200))

pdf.set_font("R", "B", 32)
pdf.set_text_color(*BLANCO)
pdf.set_xy(88, 80)
pdf.cell(34, 30, "IA", align="C")

pdf.set_font("R", "B", 27)
pdf.set_text_color(*BLANCO)
pdf.set_xy(20, 145)
pdf.cell(170, 13, "Agente de Programacion", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_xy(20, 158)
pdf.cell(170, 13, "Local con Ollama", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

pdf.set_font("R", "", 11)
pdf.set_text_color(140, 180, 230)
pdf.set_xy(20, 176)
pdf.cell(170, 7, "Documentacion Tecnica  v2.0  |  RTX 5070 100% GPU  |  Marzo 2026", align="C",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT)

for xi in range(7):
    pdf._circle(72 + xi * 10, 190, 1.5, fill=(80, 130, 200))

# Pills de modelos en portada
pdf.set_xy(22, 200)
pdf.pill("  qwen2.5-coder:7b  ", BLANCO, NARANJA)
pdf.pill("  deepseek-r1:14b  ", BLANCO, VERDE)
pdf.pill("  hermes3:8b  ", BLANCO, AZUL)

pdf.set_font("R", "", 8.5)
pdf.set_text_color(90, 120, 170)
pdf.set_xy(20, 255)
pdf.cell(170, 6, "C:\\Users\\dapio\\Documents\\ollama", align="C",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_xy(20, 263)
pdf.cell(170, 6, "Python + Ollama + CUDA 13.2 + Tool Calling   |   Marzo 2026", align="C")


# ==============================================================================
#  PAGINA 1 — Descripcion + Requisitos
# ==============================================================================
pdf.add_page()

pdf.section_title("1. Descripcion General")
pdf.body(
    "El Agente de Programacion Local es una herramienta de asistencia de codigo que funciona "
    "completamente offline utilizando modelos de lenguaje servidos por Ollama. Funciona con "
    "aceleracion GPU completa (NVIDIA RTX 5070, CUDA 13.2) y replica las capacidades principales "
    "de asistentes como Claude Code sin requerir conexion a internet ni consumir creditos de API."
)
pdf.body(
    "El agente opera en modo completamente autonomo: encadena todas las herramientas necesarias "
    "sin detenerse a pedir confirmacion entre pasos. Lee archivos, edita codigo, ejecuta comandos "
    "y busca informacion en internet de forma independiente hasta completar la tarea solicitada."
)

pdf.section_title("2. Motivacion y Objetivos")
pdf.bullet([
    "Privacidad total: el codigo del proyecto nunca sale del equipo local.",
    "Cero coste de API: sin facturacion por tokens ni limites de uso.",
    "Disponibilidad offline: funciona sin conexion (busqueda web opcional).",
    "100% GPU: aceleracion CUDA completa en modelos 7b/8b con RTX 5070.",
    "Autonomia real: encadena pasos sin interrumpir al usuario entre herramientas.",
    "Contexto de proyecto: carga automaticamente CLAUDE.md o README.md al iniciar.",
])

pdf.section_title("3. Requisitos del Sistema")
pdf.info_table(
    ["Componente", "Version", "Notas"],
    [
        ["Python",              "3.9+",    "Con pip instalado"],
        ["Ollama",              "0.18.3+", "Servidor local en http://localhost:11434"],
        ["CUDA",                "12.x+",   "Para aceleracion GPU NVIDIA"],
        ["GPU VRAM",            "8 GB+",   "RTX 5070 (12 GB) — modelos 7b/8b: 100% GPU"],
        ["ollama (libreria py)","ultima",  "pip install ollama"],
        ["rich",                "ultima",  "pip install rich"],
        ["duckduckgo-search",   "ultima",  "pip install duckduckgo-search (busqueda web)"],
        ["requests + bs4",      "ultima",  "pip install requests beautifulsoup4 (fetch URL)"],
    ],
    [38, 26, 102]
)


# ==============================================================================
#  PAGINA 2 — Comportamiento Autonomo
# ==============================================================================
pdf.add_page()

pdf.section_title("4. Comportamiento Autonomo — Modo Agentico")
pdf.body(
    "El agente esta configurado para completar tareas de principio a fin sin interrupciones. "
    "Nunca dice 'ejecuta tu este comando' ni pregunta '?quieres que continue?' entre pasos. "
    "Actua directamente con las herramientas y solo informa al usuario cuando la tarea esta completa."
)

pdf.section_title("4.1 Reglas de Comportamiento", level=2)
pdf.bullet([
    "NUNCA le dice al usuario que comandos ejecutar — los ejecuta el con run_command.",
    "NUNCA pregunta '?continuo?', '?sigo?', '?procedo?' — avanza directamente.",
    "NUNCA explica lo que va a hacer antes de hacerlo — actua y luego reporta.",
    "SIEMPRE lee un archivo con read_file antes de editarlo con edit_file.",
    "SIEMPRE explora el proyecto con list_directory si no conoce la estructura.",
    "Confirma con el usuario antes de borrar archivos o hacer cambios destructivos.",
], color=VERDE)

pdf.section_title("4.2 Flujos de Trabajo Tipicos", level=2)

pdf.section_title("Modificar codigo existente:", level=3)
pdf.code_block(
    "list_directory()  ->  find_files('**/*.py')  ->  read_file(archivo)\n"
    "->  edit_file(fix)  ->  run_command('python archivo.py')  ->  Resultado",
    "flujo: modificar codigo"
)

pdf.section_title("Crear un proyecto nuevo:", level=3)
pdf.code_block(
    "run_command('npm init -y')  ->  run_command('npm install express')\n"
    "->  write_file('index.js', ...)  ->  run_command('node index.js')  ->  Resultado",
    "flujo: nuevo proyecto"
)

pdf.section_title("Depurar un error:", level=3)
pdf.code_block(
    "run_command('python script.py')  ->  [leer el error]\n"
    "->  read_file('script.py')  ->  edit_file(correccion)\n"
    "->  run_command('python script.py')  ->  'Corregido en linea Y'",
    "flujo: depuracion"
)

pdf.section_title("4.3 Parametros del Modelo (Precision)", level=2)
pdf.info_table(
    ["Parametro", "Valor", "Efecto"],
    [
        ["temperature",    "0.1",   "Respuestas deterministicas y precisas, sin inventar"],
        ["top_p",          "0.9",   "Equilibrio entre precision y variedad"],
        ["repeat_penalty", "1.1",   "Evita respuestas repetitivas o en bucle"],
        ["num_ctx",        "16384", "Ventana de contexto amplia — 16K tokens"],
    ],
    [38, 20, 108]
)


# ==============================================================================
#  PAGINA 3 — GPU
# ==============================================================================
pdf.add_page()

pdf.section_title("5. Configuracion GPU — RTX 5070 + CUDA 13.2")
pdf.body(
    "El agente esta configurado para maximizar el uso de la GPU. Las variables de entorno "
    "se establecen permanentemente con setx y se aplican a todos los accesos directos .bat."
)

pdf.section_title("5.1 Variables de Entorno", level=2)
pdf.info_table(
    ["Variable", "Valor", "Efecto"],
    [
        ["OLLAMA_NUM_GPU",      "999", "Fuerza todas las capas del modelo en GPU"],
        ["OLLAMA_KEEP_ALIVE",   "-1",  "El modelo permanece cargado en VRAM indefinidamente"],
        ["CUDA_VISIBLE_DEVICES","0",   "Usa la GPU primaria (RTX 5070)"],
    ],
    [55, 18, 93]
)

pdf.section_title("5.2 Parametros API (por llamada)", level=2)
pdf.info_table(
    ["Parametro", "Valor", "Efecto"],
    [
        ["num_gpu",    "99",   "Offload maximo de capas al llamar al modelo"],
        ["main_gpu",   "0",    "GPU principal para inferencia"],
        ["f16_kv",     "True", "Cache KV en float16 — mas rapido en GPU"],
    ],
    [38, 18, 110]
)

pdf.section_title("5.3 Uso de VRAM por Modelo", level=2)
pdf.info_table(
    ["Modelo", "Tamano", "VRAM usada", "GPU"],
    [
        ["qwen2.5-coder:7b",        "4.7 GB", "~5.3 GB",  "100% GPU"],
        ["hermes3:8b",              "4.7 GB", "~5.3 GB",  "100% GPU"],
        ["dolphin3:8b",             "4.9 GB", "~5.5 GB",  "100% GPU"],
        ["llama3-groq-tool-use:8b", "4.7 GB", "~5.3 GB",  "100% GPU"],
        ["qwen2.5:7b",              "4.7 GB", "~5.3 GB",  "100% GPU"],
        ["deepseek-r1:14b",         "9.0 GB", "~11 GB",   "~74% GPU (14b no cabe entero)"],
        ["qwen2.5-coder:14b",       "9.0 GB", "~11 GB",   "~74% GPU (14b no cabe entero)"],
    ],
    [50, 24, 28, 64]
)

pdf.section_title("5.4 Verificar uso de GPU", level=2)
pdf.code_block(
    "# Ver modelos activos y su procesador\n"
    "ollama ps\n\n"
    "# Ver VRAM en tiempo real\n"
    "nvidia-smi\n\n"
    "# La columna PROCESSOR debe mostrar: 100% GPU (modelos 7b/8b)",
    "bash"
)


# ==============================================================================
#  PAGINA 4 — Modelos
# ==============================================================================
pdf.add_page()

pdf.section_title("6. Modelos Disponibles")

pdf.section_title("Con restricciones — IA/con censura/", level=2)
pdf.model_card(
    tag="SONNET",
    model="qwen2.5-coder:7b  [100% GPU]",
    pill_label="  Rapido y Preciso  ",
    pill_fg=BLANCO, pill_bg=NARANJA,
    desc="Especializado en codigo. 100% GPU en RTX 5070. Ideal para programacion del dia a dia.",
    items=[
        "Escritura de funciones, clases y modulos completos",
        "Edicion y refactoring de codigo existente",
        "Ejecucion de comandos y scripts",
        "Instalacion de dependencias (pip, npm, cargo)",
    ],
    cmd='python src/agent.py --model qwen2.5-coder:7b --dir "C:\\mi\\proyecto"'
)

pdf.model_card(
    tag="OPUS",
    model="deepseek-r1:14b",
    pill_label="  Razonamiento Profundo  ",
    pill_fg=BLANCO, pill_bg=VERDE,
    desc="Chain-of-thought avanzado. Para tareas complejas que requieren analisis antes de actuar.",
    items=[
        "Diseno de arquitectura de software",
        "Depuracion de bugs complejos o sutiles",
        "Revision y analisis de codigo",
        "Decisiones de diseno y trade-offs",
    ],
    cmd='python src/agent.py --model deepseek-r1:14b --dir "C:\\mi\\proyecto"'
)

pdf.section_title("Sin restricciones — IA/sin censura/", level=2)
pdf.info_table(
    ["Acceso directo", "Modelo", "Uso"],
    [
        ["DOLPHIN",        "dolphin3:8b",              "Sin censura, respuestas rapidas — 100% GPU"],
        ["HERMES",         "hermes3:8b",               "Sin censura, respuestas precisas — 100% GPU"],
        ["GROQ",           "llama3-groq-tool-use:8b",  "Optimizado para tool calling — 100% GPU"],
        ["HERMES-HACKER",  "hermes-hacker",            "Pentesting, exploits, HTB"],
        ["DOLPHIN-HACKER", "dolphin-hacker",           "Pentesting, exploits, HTB"],
    ],
    [38, 52, 76]
)


# ==============================================================================
#  PAGINA 5 — Herramientas
# ==============================================================================
pdf.add_page()

pdf.section_title("7. Herramientas del Agente — 10 Tool Calls")
pdf.body(
    "El agente dispone de 10 herramientas que el modelo invoca autonomamente. "
    "El modelo encadena multiples herramientas en secuencia sin detenerse entre ellas."
)
pdf.ln(2)

tools = [
    ("run_command",    AZUL,
     "Ejecuta comandos PowerShell o CMD con timeout configurable.",
     "Scripts, pip/npm/cargo/git, compilar, testear. Timeout default: 60s."),
    ("read_file",      VERDE,
     "Lee un archivo mostrando su contenido con numeros de linea.",
     "Uso OBLIGATORIO antes de edit_file. Rechaza archivos >2 MB."),
    ("write_file",     AZUL_LT,
     "Crea un archivo nuevo con contenido completo.",
     "Solo para archivos nuevos. Crea directorios padre automaticamente."),
    ("edit_file",      NARANJA,
     "Reemplaza texto exacto en un archivo existente (old_text -> new_text).",
     "Requiere coincidencia exacta incluyendo espacios e indentacion."),
    ("find_files",     VERDE,
     "Busca archivos por patron glob (**/*.py, src/**/*.ts, *.json).",
     "Devuelve hasta 50 resultados ordenados por nombre."),
    ("grep",           AZUL,
     "Busca texto o expresiones regex en todos los archivos del proyecto.",
     "Devuelve archivo, numero de linea y contenido. Hasta 50 coincidencias."),
    ("list_directory", AZUL_LT,
     "Lista archivos y carpetas de un directorio con tipo y tamano.",
     "Punto de partida para explorar un proyecto desconocido."),
    ("delete_file",    ROJO,
     "Elimina un archivo o directorio vacio.",
     "Operacion irreversible — el agente confirma con el usuario antes de ejecutar."),
    ("search_web",     VERDE,
     "Busca en internet con DuckDuckGo y devuelve los mejores resultados.",
     "Para noticias, documentacion, precios o cualquier informacion actual."),
    ("fetch_url",      AZUL,
     "Descarga y extrae el texto limpio de una URL (hasta 4000 caracteres).",
     "Para leer documentacion, articulos o paginas web completas."),
]

for name, accent, desc, note in tools:
    pdf.tool_card(name, desc, note, accent=accent)


# ==============================================================================
#  PAGINA 6 — Arquitectura + CLI
# ==============================================================================
pdf.add_page()

pdf.section_title("8. Arquitectura del Sistema")

pdf.section_title("8.1 Estructura de Archivos", level=2)
pdf.code_block("""\
ollama/
+-- src/
|   +-- agent.py                          # Nucleo del agente (unico archivo)
+-- docs/
|   +-- documentacion_agente_local.pdf    # Este documento
+-- scripts/
|   +-- generar_pdf.py                    # Regenera la documentacion
+-- IA/
|   +-- con censura/
|   |   +-- SONNET [qwen2.5-coder - Rapido y preciso].bat
|   |   +-- OPUS [deepseek-r1 - Razonamiento profundo].bat
|   +-- sin censura/
|       +-- DOLPHIN [dolphin3 - Sin censura rapido].bat
|       +-- HERMES [hermes3 - Sin censura preciso].bat
|       +-- GROQ [llama3-groq-tool-use - Herramientas optimizado].bat
|       +-- HERMES-HACKER [HTB - Pentesting - Exploits].bat
|       +-- DOLPHIN-HACKER [HTB - Pentesting - Exploits].bat""", "estructura del proyecto")

pdf.section_title("8.2 Flujo de Ejecucion", level=2)
pdf.step_list([
    "El usuario lanza un .bat que establece variables GPU y ejecuta agent.py.",
    "El agente carga el contexto del proyecto (CLAUDE.md / README.md / .cursorrules).",
    "Se construye el system prompt con instrucciones de autonomia, herramientas y directorio.",
    "Bucle interactivo: el usuario escribe, el modelo responde con streaming.",
    "Si el modelo llama a una herramienta, se ejecuta localmente y el resultado vuelve al modelo.",
    "El modelo encadena multiples tool calls hasta completar la tarea sin interrumpir al usuario.",
    "El historial se recorta automaticamente a los ultimos 10 pares (16K tokens de contexto).",
])

pdf.section_title("9. Parametros CLI")
pdf.code_block("""\
python src/agent.py [--model MODELO] [--dir DIRECTORIO] [--tag NOMBRE]

  --model   Modelo Ollama a usar    (default: qwen2.5-coder:7b)
  --dir     Directorio de trabajo   (default: directorio actual)
  --tag     Nombre en la cabecera   (default: AGENTE)

Ejemplos:
  python src/agent.py --model deepseek-r1:14b --dir C:\\proyectos\\miapp
  python src/agent.py --model hermes3:8b --dir . --tag HERMES""", "bash")

pdf.section_title("10. Comandos de Sesion")
pdf.info_table(
    ["Comando", "Accion"],
    [
        ["salir / exit / quit",     "Termina el agente"],
        ["limpiar / clear / reset", "Reinicia el historial de conversacion (nueva sesion)"],
    ],
    [75, 91]
)

pdf.section_title("11. Contexto de Proyecto")
pdf.body(
    "Al iniciar, el agente busca automaticamente un archivo de contexto en el directorio de trabajo "
    "e incluye su contenido en el system prompt."
)
pdf.info_table(
    ["Archivo", "Prioridad", "Descripcion"],
    [
        ["CLAUDE.md",    "1a", "Instrucciones para Claude Code y agentes IA"],
        ["README.md",    "2a", "Documentacion general del proyecto"],
        [".cursorrules", "3a", "Reglas para el editor Cursor"],
    ],
    [45, 22, 99]
)
pdf.body("Solo se carga el primero encontrado. El contenido se trunca a 3000 caracteres.")


# ==============================================================================
pdf.output(OUT)
print(f"PDF generado: {os.path.abspath(OUT)}")
