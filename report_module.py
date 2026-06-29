"""Standard report generation for the QCM analyzer.

This module intentionally uses only the Python standard library so importing
``StandardReportGenerator`` never depends on an optional GUI/reporting package.
"""

from datetime import datetime
from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


class StandardReportGenerator:
    """Generate a lightweight Word-compatible ``.docx`` report."""

    def generate(self, save_path, meta, qcm_pack, rga_df=None):
        try:
            path = Path(save_path)
            if path.suffix.lower() != ".docx":
                path = path.with_suffix(".docx")
            if path.parent:
                path.parent.mkdir(parents=True, exist_ok=True)

            document_xml = self._build_document_xml(meta or {}, qcm_pack or {}, rga_df)
            self._write_docx(path, document_xml)
            return True, f"Report saved to: {path}"
        except Exception as exc:
            return False, f"Report generation failed: {exc}"

    def _build_document_xml(self, meta, qcm_pack, rga_df):
        rows = []
        rows.append(self._paragraph("QCM Deposition Report", style="Title"))
        rows.append(self._paragraph(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}"))
        rows.append(self._paragraph("Metadata", style="Heading1"))
        for key in sorted(meta):
            rows.append(self._paragraph(f"{key}: {meta[key]}"))

        rows.append(self._paragraph("QCM Summary", style="Heading1"))
        time_data = list(qcm_pack.get("time", []))
        thick_data = list(qcm_pack.get("thick", []))
        rate_data = list(qcm_pack.get("rate", []))
        freq_data = list(qcm_pack.get("freq", []))
        rows.append(self._paragraph(f"Points: {len(time_data)}"))
        if time_data:
            rows.append(self._paragraph(f"Duration: {max(time_data):.3f} s"))
        if freq_data:
            rows.append(self._paragraph(f"Final frequency shift: {freq_data[-1]:.6f} Hz"))
        if thick_data:
            rows.append(self._paragraph(f"Final thickness: {thick_data[-1]:.6f} nm"))
        if rate_data:
            rows.append(self._paragraph(f"Final rate: {rate_data[-1]:.6f} Å/s"))

        if rga_df is not None:
            rows.append(self._paragraph("RGA Summary", style="Heading1"))
            shape = getattr(rga_df, "shape", None)
            if shape:
                rows.append(self._paragraph(f"Rows: {shape[0]}, Columns: {shape[1]}"))

        body = "".join(rows) + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>'''

    @staticmethod
    def _paragraph(text, style=None):
        style_xml = f'<w:pPr><w:pStyle w:val="{escape(style)}"/></w:pPr>' if style else ""
        return f"<w:p>{style_xml}<w:r><w:t>{escape(str(text))}</w:t></w:r></w:p>"

    @staticmethod
    def _write_docx(path, document_xml):
        content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
        rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
        with ZipFile(path, "w", ZIP_DEFLATED) as docx:
            docx.writestr("[Content_Types].xml", content_types)
            docx.writestr("_rels/.rels", rels)
            docx.writestr("word/document.xml", document_xml)
