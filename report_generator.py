"""
JobCooked — Interview Report Generator  (Single-Page Edition)
All content fits on ONE A4 page for all three interview types.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime
import os

# ── Brand colours ────────────────────────────────────────────────
ORANGE   = colors.HexColor("#f97316")
SUCCESS  = colors.HexColor("#22c55e")
WARN     = colors.HexColor("#fbbf24")
ERROR    = colors.HexColor("#ef4444")
BLUE     = colors.HexColor("#3b82f6")
TEXT     = colors.HexColor("#1e1e2e")
TEXT_MID = colors.HexColor("#555570")
TEXT_LOW = colors.HexColor("#888898")
WHITE    = colors.white
LIGHT_BG = colors.HexColor("#fff7f0")
ROW_ALT  = colors.HexColor("#fef9f5")
PAGE_W   = A4[0] - 1.2 * inch          # usable width (0.6 in margin each side)


class JobCookedReportGenerator:

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._build_styles()
        print("OK JobCooked report generator ready")

    def _build_styles(self):
        base = self.styles["Normal"]
        def ps(name, **kw):
            return ParagraphStyle(name, parent=base, **kw)
        self.s_title   = ps("JCT",  fontSize=16, textColor=WHITE,    fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=1)
        self.s_sub     = ps("JCS",  fontSize=8,  textColor=colors.HexColor("#ffe0c8"), fontName="Helvetica", alignment=TA_CENTER, spaceAfter=1)
        self.s_section = ps("JCSE", fontSize=9,  textColor=ORANGE,   fontName="Helvetica-Bold", spaceBefore=5, spaceAfter=3)
        self.s_body    = ps("JCB",  fontSize=8,  textColor=TEXT,     fontName="Helvetica", spaceAfter=2, leading=11)
        self.s_label   = ps("JCL",  fontSize=7,  textColor=TEXT_LOW, fontName="Helvetica-Bold", spaceAfter=1)
        self.s_center  = ps("JCC",  fontSize=8,  textColor=TEXT,     fontName="Helvetica", alignment=TA_CENTER, spaceAfter=1)
        self.s_footer  = ps("JCF",  fontSize=7,  textColor=TEXT_LOW, fontName="Helvetica", alignment=TA_CENTER, spaceAfter=1)
        self.s_tip     = ps("JCTP", fontSize=7.5,textColor=TEXT_MID, fontName="Helvetica", spaceAfter=2, leading=11)

    def generate_report(self, data: dict, output_path: str):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            doc = SimpleDocTemplate(
                output_path, pagesize=A4,
                topMargin=0, bottomMargin=0.3*inch,
                leftMargin=0.6*inch, rightMargin=0.6*inch,
            )
            story = []
            story += self._banner(data)
            story += self._info_and_scores(data)
            story += self._badge_row(data)
            story.append(Spacer(1, 4))
            story += self._question_table(data)
            story.append(Spacer(1, 4))
            story += self._recommendations(data)
            story += self._footer()
            doc.build(story)
            print(f"OK Report saved -> {output_path}")
            return output_path
        except Exception as e:
            print(f"FAIL Report generation failed: {e}")
            import traceback; traceback.print_exc()
            return None

    def _banner(self, data):
        type_label = {
            "resume": "Resume-Based Interview",
            "role":   "Role-Based Interview",
            "aptitude": "Aptitude Test",
        }.get(data.get("interview_type", "").lower(), "Interview")
        rows = [
            [Paragraph("JobCooked", self.s_title)],
            [Paragraph(f"{type_label} Report", self.s_sub)],
        ]
        tbl = Table(rows, colWidths=[PAGE_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), ORANGE),
            ("TOPPADDING",    (0,0), (-1, 0), 10),
            ("BOTTOMPADDING", (0,-1),(-1,-1),  8),
            ("LEFTPADDING",   (0,0), (-1,-1),  0),
            ("RIGHTPADDING",  (0,0), (-1,-1),  0),
        ]))
        return [tbl, Spacer(1, 6)]

    def _info_and_scores(self, data):
        name  = data.get("candidate_name",  "Candidate")
        email = data.get("candidate_email", "")
        date  = data.get("date", datetime.now().strftime("%d %b %Y, %I:%M %p"))
        itype = data.get("interview_type", "").capitalize()
        role  = data.get("role")
        level = data.get("level")
        cat   = data.get("category")

        info_rows = [
            [Paragraph("<b>Candidate</b>", self.s_label), Paragraph(name,  self.s_body)],
            [Paragraph("<b>Email</b>",     self.s_label), Paragraph(email, self.s_body)],
            [Paragraph("<b>Type</b>",      self.s_label), Paragraph(itype, self.s_body)],
            [Paragraph("<b>Date</b>",      self.s_label), Paragraph(date,  self.s_body)],
        ]
        if role:
            info_rows.append([Paragraph("<b>Role</b>",  self.s_label), Paragraph(role,  self.s_body)])
        if level:
            info_rows.append([Paragraph("<b>Level</b>", self.s_label), Paragraph(level, self.s_body)])
        if cat and cat != "all":
            info_rows.append([Paragraph("<b>Topic</b>", self.s_label), Paragraph(cat.capitalize(), self.s_body)])

        info_tbl = Table(info_rows, colWidths=[0.75*inch, 2.1*inch])
        info_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), LIGHT_BG),
            ("BOX",           (0,0), (-1,-1), 0.4, colors.HexColor("#e8e8f0")),
            ("INNERGRID",     (0,0), (-1,-1), 0.2, colors.HexColor("#eeeeee")),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ]))

        overall       = data.get("overall_score",  0)
        speech_score  = data.get("speech_score",   None)
        content_score = data.get("content_score",  None)

        sc_header = [
            Paragraph("<b>Metric</b>",  self.s_center),
            Paragraph("<b>Score</b>",   self.s_center),
            Paragraph("<b>Grade</b>",   self.s_center),
        ]
        sc_rows = [sc_header]
        metrics = [("Overall", overall)]
        if speech_score  is not None: metrics.append(("Speech",  speech_score))
        if content_score is not None: metrics.append(("Content", content_score))

        for label, score in metrics:
            color = self._score_color(score)
            grade = self._grade(score)
            sc_rows.append([
                Paragraph(label, self.s_center),
                Paragraph(f"<b>{score:.0f}/100</b>",
                          ParagraphStyle(f"__sc{label}", parent=self.s_center,
                                         textColor=color, fontName="Helvetica-Bold")),
                Paragraph(f"<b>{grade}</b>",
                          ParagraphStyle(f"__gr{label}", parent=self.s_center,
                                         textColor=color, fontName="Helvetica-Bold")),
            ])

        sc_tbl = Table(sc_rows, colWidths=[1.25*inch, 1.0*inch, 0.7*inch])
        sc_style = TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), ORANGE),
            ("TEXTCOLOR",     (0,0), (-1,0), WHITE),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("BOX",           (0,0), (-1,-1), 0.4, colors.HexColor("#e8e8f0")),
            ("INNERGRID",     (0,0), (-1,-1), 0.2, colors.HexColor("#eeeeee")),
        ])
        for i in range(1, len(sc_rows)):
            sc_style.add("BACKGROUND", (0,i), (-1,i), ROW_ALT if i%2==0 else WHITE)
        sc_tbl.setStyle(sc_style)

        combo = Table([[info_tbl, sc_tbl]], colWidths=[3.0*inch, 3.05*inch])
        combo.setStyle(TableStyle([
            ("VALIGN",       (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",  (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING",   (0,0), (-1,-1), 0),
            ("BOTTOMPADDING",(0,0), (-1,-1), 0),
        ]))
        return [combo, Spacer(1, 5)]

    def _badge_row(self, data):
        score = data.get("overall_score", 0)
        if   score >= 80: label, color = "Excellent",         SUCCESS
        elif score >= 60: label, color = "Good",              BLUE
        elif score >= 40: label, color = "Fair",              WARN
        else:             label, color = "Needs Improvement", ERROR

        badge_style = ParagraphStyle(
            "__badge", parent=self.s_center,
            fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")
        tbl = Table(
            [[Paragraph(f"{label}  |  Overall Score: {score:.0f} / 100", badge_style)]],
            colWidths=[PAGE_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), color),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ]))
        return [tbl]

    def _question_table(self, data):
        questions = data.get("questions", [])
        if not questions:
            return []

        elements = [Paragraph("Question Score Breakdown", self.s_section)]

        header = [
            Paragraph("<b>#</b>",        self.s_center),
            Paragraph("<b>Category</b>", self.s_center),
            Paragraph("<b>Score</b>",    self.s_center),
            Paragraph("<b>Grade</b>",    self.s_center),
            Paragraph("<b>Status</b>",   self.s_center),
        ]
        rows = [header]

        for i, q in enumerate(questions, 1):
            score    = float(q.get("score", 0))
            category = q.get("category", "General")
            grade    = self._grade(score)
            status   = self._status_label(score)
            color    = self._score_color(score)
            rows.append([
                Paragraph(f"<b>Q{i}</b>", self.s_center),
                Paragraph(category, self.s_center),
                Paragraph(f"<b>{score:.0f}/100</b>",
                          ParagraphStyle(f"__qs{i}", parent=self.s_center,
                                         textColor=color, fontName="Helvetica-Bold")),
                Paragraph(f"<b>{grade}</b>",
                          ParagraphStyle(f"__qg{i}", parent=self.s_center,
                                         textColor=color, fontName="Helvetica-Bold")),
                Paragraph(status, self.s_center),
            ])

        col_w = [0.4*inch, 2.0*inch, 1.1*inch, 0.75*inch, 1.8*inch]
        row_h = [0.26*inch] * len(rows)
        tbl   = Table(rows, colWidths=col_w, rowHeights=row_h)

        style = TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  ORANGE),
            ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
            ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("BOX",           (0,0), (-1,-1), 0.4, colors.HexColor("#e0e0f0")),
            ("INNERGRID",     (0,0), (-1,-1), 0.2, colors.HexColor("#eeeeee")),
        ])
        for i in range(1, len(rows)):
            style.add("BACKGROUND", (0,i), (-1,i), ROW_ALT if i%2==0 else WHITE)
        tbl.setStyle(style)
        elements.append(tbl)
        return elements

    def _recommendations(self, data):
        elements = [Paragraph("Recommendations", self.s_section)]

        score = data.get("overall_score",  0)
        speech= data.get("speech_score",   None)
        cont  = data.get("content_score",  None)
        itype = data.get("interview_type", "").lower()

        tips = []
        if   score >= 80: tips.append("<b>Outstanding!</b> You are well-prepared - keep this standard.")
        elif score >= 60: tips.append("<b>Good effort!</b> A bit more polish will make a big difference.")
        elif score >= 40: tips.append("<b>Fair attempt.</b> Practice structured answers before real interviews.")
        else:             tips.append("<b>Keep going!</b> Focus on fundamentals and practice consistently.")

        if speech is not None and speech < 60:
            tips.append("Reduce filler words and speak in clear, complete sentences.")
        if cont is not None and cont < 60:
            tips.append("Use the <b>STAR method</b> (Situation, Task, Action, Result) for better answers.")

        type_tips = {
            "resume":   "Review your resume projects - be ready to expand on every detail.",
            "role":     "Study job-specific tools and best practices for your target role.",
            "aptitude": "For aptitude tests, practise eliminating wrong options quickly.",
        }
        if itype in type_tips:
            tips.append(type_tips[itype])
        tips.append("<b>Practice regularly</b> - the more mock interviews, the more natural your answers.")

        tip_paras = [[Paragraph(f"  {t}", self.s_tip)] for t in tips]
        tbl = Table(tip_paras, colWidths=[PAGE_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), LIGHT_BG),
            ("BOX",           (0,0), (-1,-1), 0.4, colors.HexColor("#e0e0f0")),
            ("INNERGRID",     (0,0), (-1,-1), 0.2, colors.HexColor("#eeeeee")),
            ("LEFTPADDING",   (0,0), (-1,-1), 7),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ]))
        elements.append(tbl)
        return elements

    def _footer(self):
        return [
            Spacer(1, 6),
            HRFlowable(width="100%", thickness=0.8, color=ORANGE),
            Spacer(1, 3),
            Paragraph(
                f"Generated by JobCooked  |  "
                f"{datetime.now().strftime('%d %B %Y at %I:%M %p')}  |  "
                "Confidential - for candidate use only.",
                self.s_footer),
        ]

    @staticmethod
    def _grade(score):
        if score >= 90: return "A+"
        if score >= 80: return "A"
        if score >= 70: return "B"
        if score >= 60: return "C"
        if score >= 50: return "D"
        return "F"

    @staticmethod
    def _status_label(score):
        if score >= 80: return "Excellent"
        if score >= 60: return "Good"
        if score >= 40: return "Fair"
        return "Needs Work"

    @staticmethod
    def _score_color(score):
        if score >= 75: return SUCCESS
        if score >= 50: return WARN
        return ERROR


report_generator = JobCookedReportGenerator()