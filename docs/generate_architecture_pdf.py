"""Generate the GraphRAG architecture + workflow diagram PDF."""

from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

OUTPUT_PATH = "/Users/manojkumarmuthukumaran/Documents/Work/graphrag/docs/architecture.pdf"

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
C_BLUE_DARK   = HexColor("#1a4f8a")   # ingestion header
C_BLUE_LIGHT  = HexColor("#dbeafe")   # ingestion fill
C_BLUE_MID    = HexColor("#3b82f6")   # ingestion border

C_GREEN_DARK  = HexColor("#166534")   # storage header
C_GREEN_LIGHT = HexColor("#dcfce7")   # storage fill
C_GREEN_MID   = HexColor("#22c55e")   # storage border

C_PURPLE_DARK = HexColor("#4c1d95")   # query header
C_PURPLE_LIGHT= HexColor("#ede9fe")   # query fill
C_PURPLE_MID  = HexColor("#8b5cf6")   # query border

C_ORANGE_DARK = HexColor("#7c2d12")   # cross-cutting header
C_ORANGE_LIGHT= HexColor("#ffedd5")   # cross-cutting fill
C_ORANGE_MID  = HexColor("#f97316")   # cross-cutting border

C_GRAY_LIGHT  = HexColor("#f8fafc")
C_GRAY_MID    = HexColor("#94a3b8")
C_GRAY_DARK   = HexColor("#1e293b")
C_WHITE       = colors.white
C_ARROW       = HexColor("#475569")

FONT_BOLD   = "Helvetica-Bold"
FONT_NORMAL = "Helvetica"


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def rounded_rect(c, x, y, w, h, r=4, fill=C_WHITE, stroke=C_GRAY_MID, stroke_width=1):
    c.setLineWidth(stroke_width)
    c.setStrokeColor(stroke)
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, r, stroke=1, fill=1)


def header_box(c, x, y, w, h, text, bg, fg=C_WHITE, font_size=9):
    rounded_rect(c, x, y, w, h, r=4, fill=bg, stroke=bg)
    c.setFillColor(fg)
    c.setFont(FONT_BOLD, font_size)
    c.drawCentredString(x + w / 2, y + h / 2 - font_size / 3, text)


def component_box(c, x, y, w, h, title, subtitle="",
                  fill=C_WHITE, border=C_GRAY_MID, title_size=8, sub_size=6.5):
    rounded_rect(c, x, y, w, h, r=3, fill=fill, stroke=border, stroke_width=1.2)
    c.setFillColor(C_GRAY_DARK)
    c.setFont(FONT_BOLD, title_size)
    text_y = y + h / 2 + (title_size / 2 if subtitle else 0)
    c.drawCentredString(x + w / 2, text_y, title)
    if subtitle:
        c.setFont(FONT_NORMAL, sub_size)
        c.setFillColor(C_GRAY_MID)
        c.drawCentredString(x + w / 2, y + h / 2 - sub_size, subtitle)


def arrow(c, x1, y1, x2, y2, label="", color=C_ARROW, dashed=False):
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(1.2)
    if dashed:
        c.setDash(4, 3)
    else:
        c.setDash()

    c.line(x1, y1, x2, y2)

    # Arrowhead
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 5
    p = c.beginPath()
    p.moveTo(x2, y2)
    p.lineTo(x2 - size * math.cos(angle - 0.4), y2 - size * math.sin(angle - 0.4))
    p.lineTo(x2 - size * math.cos(angle + 0.4), y2 - size * math.sin(angle + 0.4))
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    c.setDash()

    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        c.setFont(FONT_NORMAL, 6)
        c.setFillColor(C_GRAY_DARK)
        c.drawCentredString(mx, my + 3, label)


def section_panel(c, x, y, w, h, title, header_color, border_color, fill_color):
    """Draw a labelled section panel."""
    rounded_rect(c, x, y, w, h, r=6, fill=fill_color, stroke=border_color, stroke_width=1.5)
    header_box(c, x, y + h - 14, w, 14, title, header_color, font_size=8.5)


# ---------------------------------------------------------------------------
# Page 1 — Component Architecture
# ---------------------------------------------------------------------------

def draw_architecture(c, W, H):
    # Background
    c.setFillColor(C_GRAY_LIGHT)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Title
    c.setFillColor(C_GRAY_DARK)
    c.setFont(FONT_BOLD, 16)
    c.drawCentredString(W / 2, H - 20*mm, "GraphRAG — Component Architecture")
    c.setFont(FONT_NORMAL, 8)
    c.setFillColor(C_GRAY_MID)
    c.drawCentredString(W / 2, H - 25*mm, "Document graph (DocEntity) · Code graph (Entity) · Separated by label, same Neo4j instance")

    margin = 12*mm
    top    = H - 32*mm
    bottom = 18*mm
    panel_h = top - bottom

    col_w  = (W - 2 * margin) / 3 - 4*mm
    col1_x = margin
    col2_x = col1_x + col_w + 6*mm
    col3_x = col2_x + col_w + 6*mm

    # ── INGESTION PANEL ──────────────────────────────────────────────────
    section_panel(c, col1_x, bottom, col_w, panel_h,
                  "INGESTION PIPELINE", C_BLUE_DARK, C_BLUE_MID, C_BLUE_LIGHT)

    bw, bh = col_w - 10*mm, 11*mm
    bx = col1_x + 5*mm

    # Document path label
    c.setFont(FONT_BOLD, 7)
    c.setFillColor(C_BLUE_DARK)
    c.drawString(bx, bottom + panel_h - 22*mm, "Document Path")

    doc_boxes = [
        ("PDF / Text", "Input files"),
        ("chunker.py", "Sliding window split"),
        ("reader_agent.py", "Haiku extraction"),
        ("graph_writer.py", "Dedup + write"),
    ]
    doc_ys = []
    dy = bottom + panel_h - 27*mm
    for title, sub in doc_boxes:
        component_box(c, bx, dy - bh, bw, bh, title, sub,
                      fill=C_WHITE, border=C_BLUE_MID)
        doc_ys.append(dy - bh + bh / 2)
        if title != doc_boxes[-1][0]:
            arrow(c, bx + bw / 2, dy - bh, bx + bw / 2, dy - bh - 3*mm, color=C_BLUE_MID)
        dy -= bh + 3.5*mm

    # Code path label
    c.setFont(FONT_BOLD, 7)
    c.setFillColor(C_BLUE_DARK)
    c.drawString(bx, dy - 3*mm, "Code Path")

    code_boxes = [
        ("Repo Files", "Source code"),
        ("hierarchy_builder.py", "Project→Folder→File"),
        ("code_parser.py", "tree-sitter (local)"),
        ("code_normalizer.py", "Haiku optional"),
        ("code_graph_client.py", "Write to Neo4j"),
    ]
    code_ys = []
    dy -= 7*mm
    for title, sub in code_boxes:
        component_box(c, bx, dy - bh, bw, bh, title, sub,
                      fill=C_WHITE, border=C_BLUE_MID)
        code_ys.append(dy - bh + bh / 2)
        if title != code_boxes[-1][0]:
            arrow(c, bx + bw / 2, dy - bh, bx + bw / 2, dy - bh - 3*mm, color=C_BLUE_MID)
        dy -= bh + 3.5*mm

    # file_watcher feedback
    fw_y = dy - 2*mm
    component_box(c, bx, fw_y - bh, bw, bh, "file_watcher.py", "watchdog Observer",
                  fill=HexColor("#eff6ff"), border=C_BLUE_MID)
    arrow(c, bx + bw / 2, fw_y, bx + bw / 2, fw_y + 2*mm, color=C_BLUE_MID, dashed=True)
    c.setFont(FONT_NORMAL, 5.5)
    c.setFillColor(C_BLUE_DARK)
    c.drawCentredString(bx + bw / 2, fw_y + 3.5*mm, "re-parse on save")

    # ── STORAGE PANEL ────────────────────────────────────────────────────
    section_panel(c, col2_x, bottom, col_w, panel_h,
                  "STORAGE — Neo4j (Community)", C_GREEN_DARK, C_GREEN_MID, C_GREEN_LIGHT)

    sx = col2_x + 5*mm
    sw = col_w - 10*mm
    smid = bottom + panel_h / 2

    # DB outer box
    rounded_rect(c, sx, smid - 28*mm, sw, 56*mm, r=5,
                 fill=C_WHITE, stroke=C_GREEN_MID, stroke_width=2)
    c.setFont(FONT_BOLD, 8)
    c.setFillColor(C_GREEN_DARK)
    c.drawCentredString(col2_x + col_w / 2, smid + 26*mm, "neo4j default database")

    # DocEntity section
    rounded_rect(c, sx + 3*mm, smid - 2*mm, sw - 6*mm, 22*mm, r=3,
                 fill=C_BLUE_LIGHT, stroke=C_BLUE_MID, stroke_width=1)
    c.setFont(FONT_BOLD, 7.5)
    c.setFillColor(C_BLUE_DARK)
    c.drawCentredString(col2_x + col_w / 2, smid + 17*mm, "(:DocEntity)")
    c.setFont(FONT_NORMAL, 6.5)
    c.setFillColor(C_GRAY_DARK)
    c.drawCentredString(col2_x + col_w / 2, smid + 11*mm, "id · name · type")
    c.drawCentredString(col2_x + col_w / 2, smid + 6*mm, "-[:RELATION {type, weight}]->")
    c.drawCentredString(col2_x + col_w / 2, smid + 1.5*mm, "Documents · Facts · Concepts")

    # divider
    c.setStrokeColor(C_GREEN_MID)
    c.setLineWidth(0.5)
    c.line(sx + 5*mm, smid - 3*mm, sx + sw - 5*mm, smid - 3*mm)

    # Entity section
    rounded_rect(c, sx + 3*mm, smid - 26*mm, sw - 6*mm, 22*mm, r=3,
                 fill=C_PURPLE_LIGHT, stroke=C_PURPLE_MID, stroke_width=1)
    c.setFont(FONT_BOLD, 7.5)
    c.setFillColor(C_PURPLE_DARK)
    c.drawCentredString(col2_x + col_w / 2, smid - 7*mm, "(:Project/:Folder/:File/:Entity)")
    c.setFont(FONT_NORMAL, 6.5)
    c.setFillColor(C_GRAY_DARK)
    c.drawCentredString(col2_x + col_w / 2, smid - 13*mm, "project · name · type · file · line")
    c.drawCentredString(col2_x + col_w / 2, smid - 18*mm, "-[:CONTAINS / :RELATION {type}]->")
    c.drawCentredString(col2_x + col_w / 2, smid - 23*mm, "Code graph — separated by label")

    # Label separator note
    c.setFont(FONT_BOLD, 6)
    c.setFillColor(C_GREEN_DARK)
    c.drawCentredString(col2_x + col_w / 2, smid - 33*mm, "Label-based isolation · no Enterprise needed")

    # bridge_detector note
    component_box(c, sx, bottom + 6*mm, sw, 10*mm, "bridge_detector.py",
                  "BRIDGE edges across projects",
                  fill=C_ORANGE_LIGHT, border=C_ORANGE_MID)

    # ── QUERY PANEL ──────────────────────────────────────────────────────
    section_panel(c, col3_x, bottom, col_w, panel_h,
                  "QUERY LAYER", C_PURPLE_DARK, C_PURPLE_MID, C_PURPLE_LIGHT)

    qx = col3_x + 5*mm
    qw = col_w - 10*mm
    qbh = 11*mm

    c.setFont(FONT_BOLD, 7)
    c.setFillColor(C_PURPLE_DARK)
    c.drawString(qx, bottom + panel_h - 22*mm, "Document Queries")

    qy = bottom + panel_h - 27*mm
    doc_q_boxes = [
        ("query_cli.py", "BFS traversal"),
        ("agentic_agent.py", "Haiku + Sonnet synthesis"),
        ("graph_context_agent.py", "Full-graph cached mode"),
        ("seed_finder.py", "LLM-grounded seeds"),
    ]
    for title, sub in doc_q_boxes:
        component_box(c, qx, qy - qbh, qw, qbh, title, sub,
                      fill=C_WHITE, border=C_PURPLE_MID)
        qy -= qbh + 3.5*mm

    c.setFont(FONT_BOLD, 7)
    c.setFillColor(C_PURPLE_DARK)
    c.drawString(qx, qy - 3*mm, "Code Queries")
    qy -= 7*mm

    code_q_boxes = [
        ("code_query_cli.py", "--impact / --deps / --styles"),
        ("", "--trace / --tree / --cross-project"),
        ("db_router.py", "Routes by project scope"),
    ]
    for title, sub in code_q_boxes:
        if not title:
            c.setFont(FONT_NORMAL, 6.5)
            c.setFillColor(C_GRAY_MID)
            c.drawCentredString(qx + qw / 2, qy - 2*mm, sub)
            qy -= 5*mm
            continue
        component_box(c, qx, qy - qbh, qw, qbh, title, sub,
                      fill=C_WHITE, border=C_PURPLE_MID)
        qy -= qbh + 3.5*mm

    # CLI entry point
    component_box(c, qx, bottom + 18*mm, qw, qbh, "main.py",
                  "ingest · ingest-code · query · resolve · dedupe-edges",
                  fill=C_GRAY_DARK, border=C_GRAY_DARK, title_size=8)
    c.setFillColor(C_WHITE)
    c.setFont(FONT_BOLD, 8)
    c.drawCentredString(qx + qw / 2, bottom + 18*mm + qbh / 2 + 1, "main.py")
    c.setFont(FONT_NORMAL, 5.8)
    c.setFillColor(HexColor("#cbd5e1"))
    c.drawCentredString(qx + qw / 2, bottom + 18*mm + 2.5, "ingest · ingest-code · query · resolve · dedupe-edges")

    # ── CROSS-CUTTING STRIP ──────────────────────────────────────────────
    strip_h = 13*mm
    section_panel(c, margin, bottom - strip_h - 3*mm, W - 2*margin, strip_h,
                  "CROSS-CUTTING", C_ORANGE_DARK, C_ORANGE_MID, C_ORANGE_LIGHT)

    cc_items = [
        ("config.py", "Neo4j + Anthropic"),
        ("models/types.py", "Entity · Relation · Triple"),
        ("models/code_types.py", "CodeTriple · FileNode"),
        ("on_file_change.py", "PostToolUse hook"),
        (".claude/settings.json", "Hook config"),
        ("CLAUDE.md", "Claude Code instructions"),
    ]
    iw = (W - 2*margin - 10*mm) / len(cc_items)
    ix = margin + 5*mm
    iy = bottom - strip_h - 3*mm + 1*mm
    for title, sub in cc_items:
        component_box(c, ix, iy, iw - 2*mm, strip_h - 3*mm, title, sub,
                      fill=C_WHITE, border=C_ORANGE_MID, title_size=7)
        ix += iw

    # ── INTER-PANEL ARROWS ────────────────────────────────────────────────
    # Ingestion → Storage (doc)
    arrow(c, col1_x + col_w, bottom + panel_h - 60*mm,
             col2_x,          bottom + panel_h - 35*mm,
             label="DocEntity", color=C_BLUE_MID)

    # Ingestion → Storage (code)
    arrow(c, col1_x + col_w, bottom + panel_h - 100*mm,
             col2_x,          bottom + panel_h - 70*mm,
             label="Entity", color=C_PURPLE_MID)

    # Storage → Query (doc)
    arrow(c, col2_x + col_w, bottom + panel_h - 35*mm,
             col3_x,          bottom + panel_h - 35*mm,
             label="query DocEntity", color=C_BLUE_MID)

    # Storage → Query (code)
    arrow(c, col2_x + col_w, bottom + panel_h - 70*mm,
             col3_x,          bottom + panel_h - 70*mm,
             label="query Entity", color=C_PURPLE_MID)

    # Legend
    _draw_legend(c, margin, bottom - strip_h - 20*mm)


def _draw_legend(c, x, y):
    items = [
        (C_BLUE_MID,   "Ingestion pipeline"),
        (C_GREEN_MID,  "Storage layer"),
        (C_PURPLE_MID, "Query layer"),
        (C_ORANGE_MID, "Cross-cutting concerns"),
    ]
    c.setFont(FONT_BOLD, 7)
    c.setFillColor(C_GRAY_DARK)
    c.drawString(x, y, "Legend:")
    lx = x + 18*mm
    for color, label in items:
        c.setFillColor(color)
        c.rect(lx, y - 1*mm, 8*mm, 4*mm, fill=1, stroke=0)
        c.setFillColor(C_GRAY_DARK)
        c.setFont(FONT_NORMAL, 7)
        c.drawString(lx + 10*mm, y, label)
        lx += 48*mm


# ---------------------------------------------------------------------------
# Page 2 — Ingestion Workflow
# ---------------------------------------------------------------------------

def draw_workflow(c, W, H):
    c.setFillColor(C_GRAY_LIGHT)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(C_GRAY_DARK)
    c.setFont(FONT_BOLD, 16)
    c.drawCentredString(W / 2, H - 20*mm, "GraphRAG — ingest-code Workflow")
    c.setFont(FONT_NORMAL, 8)
    c.setFillColor(C_GRAY_MID)
    c.drawCentredString(W / 2, H - 25*mm, "python main.py ingest-code <repo> --project <name> [--skip-normalize]")

    # ── MAIN FLOW ─────────────────────────────────────────────────────────
    phases = [
        {
            "label": "Phase 1",
            "title": "Build Hierarchy",
            "color_dark": C_BLUE_DARK,
            "color_mid": C_BLUE_MID,
            "color_light": C_BLUE_LIGHT,
            "steps": [
                ("os.walk(repo)", "Traverse directory tree"),
                ("hierarchy_builder.py", "Walk skipping: node_modules,\ncoverage, .git, dist, tmp…"),
                ("MERGE :Project node", "Stable UUID from project name"),
                ("MERGE :Folder nodes", "One per directory, depth tagged"),
                ("MERGE :File nodes", "Source files only (.py .ts .html…)"),
                ("MERGE :CONTAINS edges", "Links each level to its parent"),
                ("→ file_id_map", "rel_path → neo4j node ID"),
            ],
        },
        {
            "label": "Phase 2",
            "title": "Parse Source Files",
            "color_dark": C_BLUE_DARK,
            "color_mid": HexColor("#2563eb"),
            "color_light": HexColor("#bfdbfe"),
            "steps": [
                ("parse_directory()", "Collect all source file paths"),
                ("tqdm progress bar", "N files · file/s"),
                ("parse_file(path)", "Per file, catches errors silently"),
                ("tree-sitter Parser", "Local AST — no API call"),
                ("_walk(root_node)", "Depth-first node traversal"),
                ("→ CodeTriple list", "from · rel_type · to · file · line"),
                ("~59,990 triples", "For 3,006 files (frontend)"),
            ],
        },
        {
            "label": "Phase 3",
            "title": "Normalize (optional)",
            "color_dark": C_PURPLE_DARK,
            "color_mid": C_PURPLE_MID,
            "color_light": C_PURPLE_LIGHT,
            "steps": [
                ("--skip-normalize?", "If set → skip to Phase 4"),
                ("Split into batches", "75 triples per batch"),
                ("tqdm progress bar", "N batches · batch/s"),
                ("Claude Haiku", "Names + relation types only\n(no source code sent)"),
                ("Resolve aliases", "e.g. db → DatabaseClient"),
                ("Reclassify relations", "Fix parser mis-tags"),
                ("→ corrected triples", "Fallback to originals on error"),
            ],
        },
        {
            "label": "Phase 4",
            "title": "Write to Neo4j",
            "color_dark": C_GREEN_DARK,
            "color_mid": C_GREEN_MID,
            "color_light": C_GREEN_LIGHT,
            "steps": [
                ("tqdm progress bar", "N triples · triple/s"),
                ("write_code_triple()", "Per triple"),
                ("MERGE :Entity (from)", "project-scoped UUID"),
                ("MERGE :Entity (to)", "project-scoped UUID"),
                ("MERGE :RELATION", "Idempotent — safe to re-run"),
                ("MERGE :CONTAINS", "Entity → File node link"),
                ("node_count()", "Final stats printout"),
            ],
        },
    ]

    panel_w = (W - 28*mm) / 4
    panel_h = H - 55*mm
    px = 12*mm
    py = 18*mm

    for phase in phases:
        cd = phase["color_dark"]
        cm = phase["color_mid"]
        cl = phase["color_light"]

        # Panel background
        rounded_rect(c, px, py, panel_w - 4*mm, panel_h, r=6,
                     fill=cl, stroke=cm, stroke_width=1.5)
        # Header
        header_box(c, px, py + panel_h - 14*mm, panel_w - 4*mm, 14*mm,
                   f"{phase['label']} — {phase['title']}", cd, font_size=8.5)

        # Steps
        step_h = (panel_h - 22*mm) / len(phase["steps"])
        sy = py + panel_h - 22*mm

        for i, (title, subtitle) in enumerate(phase["steps"]):
            is_last = i == len(phase["steps"]) - 1
            sh = step_h - 2*mm

            # Alternating tint
            fill = C_WHITE if i % 2 == 0 else HexColor("#f0f9ff")
            rounded_rect(c, px + 3*mm, sy - sh, panel_w - 10*mm, sh - 1*mm,
                         r=3, fill=fill, stroke=cm, stroke_width=0.8)

            c.setFont(FONT_BOLD, 7.5)
            c.setFillColor(cd)
            lines = title.split("\n")
            if len(lines) == 1:
                c.drawCentredString(px + (panel_w - 4*mm) / 2,
                                    sy - sh / 2 + (3 if subtitle else 0), title)
            else:
                for li, l in enumerate(lines):
                    c.drawCentredString(px + (panel_w - 4*mm) / 2,
                                        sy - sh / 2 + 4 - li * 8, l)

            if subtitle:
                c.setFont(FONT_NORMAL, 6)
                c.setFillColor(C_GRAY_MID)
                for li, sl in enumerate(subtitle.split("\n")):
                    c.drawCentredString(px + (panel_w - 4*mm) / 2,
                                        sy - sh / 2 - 4 - li * 7, sl)

            # Connector arrow between steps
            if not is_last:
                arrow(c,
                      px + (panel_w - 4*mm) / 2, sy - sh - 1*mm,
                      px + (panel_w - 4*mm) / 2, sy - sh - 2.5*mm,
                      color=cm)

            sy -= step_h

        # Arrow to next phase
        if phase != phases[-1]:
            arrow(c,
                  px + panel_w - 4*mm, py + panel_h / 2,
                  px + panel_w,        py + panel_h / 2,
                  color=C_GRAY_DARK)

        px += panel_w

    # ── PostToolUse Hook strip ────────────────────────────────────────────
    strip_y = py - 15*mm
    strip_h = 12*mm
    strip_w = W - 24*mm

    rounded_rect(c, 12*mm, strip_y, strip_w, strip_h, r=5,
                 fill=C_ORANGE_LIGHT, stroke=C_ORANGE_MID, stroke_width=1.5)
    header_box(c, 12*mm, strip_y + strip_h - 7*mm, strip_w, 7*mm,
               "PostToolUse Hook (incremental updates — triggered by every Claude Code Write/Edit)",
               C_ORANGE_DARK, font_size=7.5)

    hook_steps = [
        "Claude Code\nWrite / Edit",
        "on_file_change.py\nreads stdin JSON",
        "Extract file_path\nfrom hook payload",
        "delete_file_triples()\nRemove stale entities",
        "parse_file()\ntree-sitter re-parse",
        "write_code_triple()\nWrite fresh triples",
        "Graph stays\nin sync ✓",
    ]
    hw = (strip_w - 6*mm) / len(hook_steps)
    hx = 15*mm
    for i, step in enumerate(hook_steps):
        is_last = i == len(hook_steps) - 1
        rounded_rect(c, hx, strip_y + 1.5*mm, hw - 2*mm, strip_h - 9*mm,
                     r=2, fill=C_WHITE, stroke=C_ORANGE_MID, stroke_width=0.8)
        c.setFont(FONT_NORMAL, 5.8)
        c.setFillColor(C_GRAY_DARK)
        lines = step.split("\n")
        for li, l in enumerate(lines):
            c.drawCentredString(hx + (hw - 2*mm) / 2,
                                strip_y + 4*mm + (4 if len(lines) > 1 else 0) - li * 7, l)
        if not is_last:
            arrow(c, hx + hw - 2*mm, strip_y + strip_h / 2 - 3*mm,
                     hx + hw,         strip_y + strip_h / 2 - 3*mm,
                     color=C_ORANGE_MID)
        hx += hw


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_pdf():
    W, H = landscape(A3)
    c = canvas.Canvas(OUTPUT_PATH, pagesize=(W, H))

    # Page 1
    c.setTitle("GraphRAG Architecture")
    c.setAuthor("GraphRAG")
    draw_architecture(c, W, H)
    c.showPage()

    # Page 2
    draw_workflow(c, W, H)
    c.showPage()

    c.save()
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
