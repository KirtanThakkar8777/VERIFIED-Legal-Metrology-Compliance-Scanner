"""
report/pdf_gen.py â€” ReportLab PDF generator for compliance reports.
"""
from __future__ import annotations
from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# Brand colours
CREAM      = colors.HexColor("#f5f0e8")
NAVY       = colors.HexColor("#1a1a2e")
GOLD       = colors.HexColor("#8b6914")
RED        = colors.HexColor("#C41E3A")
GREEN      = colors.HexColor("#16a34a")
ORANGE     = colors.HexColor("#d97706")
LIGHT_GREY = colors.HexColor("#e5e0d8")
DARK_GREY  = colors.HexColor("#6b6b6b")


def _status_color(status: str) -> colors.Color:
    return {"PASS": GREEN, "FAIL": RED, "REVIEW": ORANGE}.get(status, NAVY)


def _p(text: str, style) -> Paragraph:
    """Wrap text in a Paragraph for proper line-wrapping inside table cells."""
    return Paragraph(str(text or "â€”"), style)


def generate_pdf(scan) -> bytes:
    """Generate a formatted compliance notice PDF. Returns raw bytes."""
    buf = BytesIO()

    # A4 usable width = 210mm - 20mm*2 margins = 170mm
    PAGE_W = 170 * mm

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title", parent=styles["Title"],
        fontSize=18, textColor=NAVY, spaceAfter=4,
        alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    sub_style = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        fontSize=9, textColor=GOLD, alignment=TA_CENTER, fontName="Helvetica",
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=9, textColor=NAVY, fontName="Helvetica", leading=13,
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"],
        fontSize=9, textColor=GOLD, fontName="Helvetica-Bold", spaceAfter=2,
    )
    # Cell label (left column gold text)
    cell_label_style = ParagraphStyle(
        "CellLabel", parent=styles["Normal"],
        fontSize=8, textColor=GOLD, fontName="Helvetica-Bold", leading=11,
    )
    # Cell value (regular text, wraps)
    cell_val_style = ParagraphStyle(
        "CellVal", parent=styles["Normal"],
        fontSize=8, textColor=NAVY, fontName="Helvetica", leading=11,
    )
    # Small style for field table
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontSize=7.5, textColor=NAVY, fontName="Helvetica", leading=10,
    )
    small_bold_style = ParagraphStyle(
        "SmallBold", parent=styles["Normal"],
        fontSize=7.5, textColor=NAVY, fontName="Helvetica-Bold", leading=10,
    )

    story = []

    # â”€â”€ Header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("VERIFIED v2", title_style))
    story.append(Paragraph(
        "Legal Metrology (Packaged Commodities) Rules 2011 â€” Compliance Notice",
        sub_style,
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD))
    story.append(Spacer(1, 4 * mm))

    # â”€â”€ Meta table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Col widths: [label_L, value_L, label_R, value_R] = 170mm total
    # Label cols = 25mm each, value cols split remaining 120mm as 70 / 50
    META_COLS = [25 * mm, 70 * mm, 25 * mm, 50 * mm]

    verdict_color = _status_color(scan.status)
    verdict_style = ParagraphStyle(
        "Verdict", parent=cell_val_style,
        textColor=verdict_color, fontName="Helvetica-Bold",
    )

    # Truncate product name at 120 chars to avoid excessive wrapping
    product_name = scan.product_name or "Unknown"
    if len(product_name) > 120:
        product_name = product_name[:117] + "..."

    meta_data = [
        [
            _p("Scan ID",     cell_label_style),
            _p(scan.id,       cell_val_style),
            _p("Verdict",     cell_label_style),
            _p(scan.status,   verdict_style),
        ],
        [
            _p("Product",     cell_label_style),
            _p(product_name,  cell_val_style),
            _p("Score",       cell_label_style),
            _p(f"{scan.score} / 100", cell_val_style),
        ],
        [
            _p("Category",    cell_label_style),
            _p(scan.category or "â€”", cell_val_style),
            _p("Rule Set",    cell_label_style),
            _p(scan.rule_version or "â€”", cell_val_style),
        ],
        [
            _p("Platform",    cell_label_style),
            _p(scan.platform or "â€”", cell_val_style),
            _p("Source",      cell_label_style),
            _p(scan.source_type or "â€”", cell_val_style),
        ],
        [
            _p("Scanned On",  cell_label_style),
            _p(scan.created_at.strftime("%d %b %Y, %H:%M UTC"), cell_val_style),
            _p("", cell_val_style),
            _p("", cell_val_style),
        ],
    ]

    meta_table = Table(meta_data, colWidths=META_COLS)
    meta_table.setStyle(TableStyle([
        ("GRID",          (0, 0), (-1, -1), 0.3, LIGHT_GREY),
        ("BACKGROUND",    (0, 0), (-1, -1), CREAM),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        # Span last row label+value across remaining cols (Scanned On row)
        ("SPAN",          (1, 4), (3, 4)),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6 * mm))

    # â”€â”€ Field results table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("FIELD RESULTS", label_style))
    story.append(Spacer(1, 2 * mm))

    # Col widths: Field | Legal Ref | Status | Detected Value = 170mm
    # 55 + 40 + 18 + 57 = 170mm
    FIELD_COLS = [55 * mm, 40 * mm, 18 * mm, 57 * mm]

    hdr_style = ParagraphStyle(
        "HdrCell", parent=styles["Normal"],
        fontSize=8, textColor=CREAM, fontName="Helvetica-Bold", leading=10,
    )

    field_data = [[
        _p("Field",          hdr_style),
        _p("Legal Ref",      hdr_style),
        _p("Status",         hdr_style),
        _p("Detected Value", hdr_style),
    ]]

    for f in scan.fields:
        sc = _status_color(f.status)
        status_style = ParagraphStyle(
            f"FS_{f.field_id}", parent=small_style,
            textColor=sc, fontName="Helvetica-Bold",
        )

        # Detected value â€” wrap long values at 80 chars
        val = f.normalized_value or f.detected_value or "â€”"
        if len(val) > 80:
            val = val[:77] + "..."

        field_data.append([
            _p(f.field_label,      small_style),
            _p(f.legal_reference,  small_style),
            _p(f.status,           status_style),
            _p(val,                small_style),
        ])

    field_table = Table(field_data, colWidths=FIELD_COLS, repeatRows=1)
    field_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("GRID",          (0, 0), (-1, -1), 0.3, LIGHT_GREY),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [CREAM, colors.white]),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    story.append(field_table)

    # â”€â”€ Violations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if scan.violations:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("VIOLATIONS &amp; DEFICIENCIES", label_style))
        story.append(Spacer(1, 2 * mm))

        for v in scan.violations:
            sc = RED if v.severity == "high" else ORANGE
            viol_hdr_style = ParagraphStyle(
                "VH", parent=body_style, textColor=sc, fontName="Helvetica-Bold",
            )
            story.append(Paragraph(
                f"[{v.severity.upper()}]  {v.field_label} â€” {v.legal_reference}",
                viol_hdr_style,
            ))
            story.append(Paragraph(v.reason or "", small_style))
            story.append(Spacer(1, 3 * mm))

    # â”€â”€ Footer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GOLD))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Generated by VERIFIED v2 â€” Automated Legal Metrology Compliance Scanner  |  "
        f"Report Date: {datetime.utcnow().strftime('%d %b %Y')}",
        ParagraphStyle("Footer", parent=small_style, textColor=GOLD, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()
