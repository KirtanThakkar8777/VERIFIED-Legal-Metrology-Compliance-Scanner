"""
report/pdf_gen.py — ReportLab PDF generator for compliance reports.
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
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# Brand colours
CREAM = colors.HexColor("#f5f0e8")
NAVY = colors.HexColor("#1a1a2e")
GOLD = colors.HexColor("#8b6914")
RED = colors.HexColor("#C41E3A")
GREEN = colors.HexColor("#16a34a")
ORANGE = colors.HexColor("#d97706")
LIGHT_GREY = colors.HexColor("#e5e0d8")


def _status_color(status: str) -> colors.Color:
    return {"PASS": GREEN, "FAIL": RED, "REVIEW": ORANGE}.get(status, NAVY)


def generate_pdf(scan) -> bytes:
    """Generate a formatted compliance notice PDF. Returns raw bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Title"],
        fontSize=16, textColor=NAVY, spaceAfter=4,
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
        fontSize=8, textColor=GOLD, fontName="Helvetica-Bold",
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontSize=7.5, textColor=NAVY, fontName="Helvetica",
    )

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("VERIFIED v2", title_style))
    story.append(Paragraph(
        "Legal Metrology (Packaged Commodities) Rules 2011 — Compliance Notice",
        sub_style,
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD))
    story.append(Spacer(1, 4 * mm))

    # ── Meta table ────────────────────────────────────────────────────────────
    verdict_color = _status_color(scan.status)
    meta_data = [
        ["Scan ID", scan.id, "Verdict", Paragraph(f"<b>{scan.status}</b>", body_style)],
        ["Product", scan.product_name, "Score", f"{scan.score} / 100"],
        ["Category", scan.category, "Rule Set", scan.rule_version],
        ["Platform", scan.platform, "Source", scan.source_type],
        ["Scanned On", scan.created_at.strftime("%d %b %Y, %H:%M UTC"), "", ""],
    ]
    meta_table = Table(meta_data, colWidths=[35 * mm, 65 * mm, 30 * mm, 40 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (0, -1), GOLD),
        ("TEXTCOLOR", (2, 0), (2, -1), GOLD),
        ("TEXTCOLOR", (1, 0), (1, -1), NAVY),
        ("TEXTCOLOR", (3, 0), (3, -1), NAVY),
        ("TEXTCOLOR", (3, 0), (3, 0), verdict_color),
        ("FONTNAME", (3, 0), (3, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.3, LIGHT_GREY),
        ("BACKGROUND", (0, 0), (-1, -1), CREAM),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6 * mm))

    # ── Field results table ───────────────────────────────────────────────────
    story.append(Paragraph("FIELD RESULTS", label_style))
    story.append(Spacer(1, 2 * mm))

    field_data = [["Field", "Legal Ref", "Status", "Detected Value"]]
    for f in scan.fields:
        sc = _status_color(f.status)
        val = f.normalized_value or f.detected_value or "—"
        if len(val) > 45:
            val = val[:42] + "..."
        field_data.append([
            Paragraph(f.field_label, small_style),
            Paragraph(f.legal_reference, small_style),
            Paragraph(f"<b>{f.status}</b>", ParagraphStyle(
                "FS", parent=small_style, textColor=sc, fontName="Helvetica-Bold",
            )),
            Paragraph(val, small_style),
        ])

    col_w = [55 * mm, 30 * mm, 18 * mm, 65 * mm]
    field_table = Table(field_data, colWidths=col_w, repeatRows=1)
    field_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), CREAM),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, LIGHT_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CREAM, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(field_table)

    # ── Violations ────────────────────────────────────────────────────────────
    if scan.violations:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("VIOLATIONS & DEFICIENCIES", label_style))
        story.append(Spacer(1, 2 * mm))

        for v in scan.violations:
            sc = RED if v.severity == "high" else ORANGE
            story.append(Paragraph(
                f"<b>[{v.severity.upper()}]</b> {v.field_label} — {v.legal_reference}",
                ParagraphStyle("VH", parent=body_style, textColor=sc, fontName="Helvetica-Bold"),
            ))
            story.append(Paragraph(v.reason, small_style))
            story.append(Spacer(1, 2 * mm))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GOLD))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Generated by VERIFIED v2 — Automated Legal Metrology Compliance Scanner  |  "
        f"Report Date: {datetime.utcnow().strftime('%d %b %Y')}",
        ParagraphStyle("Footer", parent=small_style, textColor=GOLD, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()
