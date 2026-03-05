"""
Report generation operations for A.N.K.I.T.A.
Builds structured reports with data, charts, and exports to PDF/Markdown.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def generate_pdf(
    title: str,
    sections: List[Dict[str, Any]],
    output_path: Optional[str] = None,
    format: str = "pdf",
    **kwargs
) -> Dict[str, Any]:
    """
    Generate a structured report document.
    
    Args:
        title: Report title
        sections: List of section dicts with 'heading', 'content', 'type' (text/table/chart)
        output_path: Where to save the report (defaults to Desktop)
        format: Output format - 'pdf' or 'md' (markdown)
    
    Returns:
        Dict with status and file path
    """
    try:
        # Default output location
        if not output_path:
            desktop = Path.home() / "Desktop"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{title.replace(' ', '_')}_{timestamp}.{format}"
            output_path = str(desktop / filename)
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "md":
            return _generate_markdown(title, sections, output_path)
        elif format == "pdf":
            return _generate_pdf_report(title, sections, output_path)
        else:
            return {"status": "error", "error": f"Unsupported format: {format}"}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _generate_markdown(title: str, sections: List[Dict[str, Any]], output_path: Path) -> Dict[str, Any]:
    """Generate a Markdown report."""
    lines = [
        f"# {title}",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "---",
        ""
    ]
    
    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", "")
        section_type = section.get("type", "text")
        
        if heading:
            lines.append(f"## {heading}")
            lines.append("")
        
        if section_type == "text":
            lines.append(content)
            lines.append("")
        
        elif section_type == "table":
            # Content should be a list of dicts or a dict with 'headers' and 'rows'
            if isinstance(content, dict) and "headers" in content:
                headers = content["headers"]
                rows = content["rows"]
            elif isinstance(content, list) and content:
                # Infer headers from first dict
                headers = list(content[0].keys())
                rows = [[str(row.get(h, "")) for h in headers] for row in content]
            else:
                lines.append("*No table data*")
                lines.append("")
                continue
            
            # Build markdown table
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
            lines.append("")
        
        elif section_type == "list":
            items = content if isinstance(content, list) else [content]
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
        
        elif section_type == "code":
            lang = section.get("language", "")
            lines.append(f"```{lang}")
            lines.append(content)
            lines.append("```")
            lines.append("")
        
        else:
            lines.append(str(content))
            lines.append("")
    
    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return {
        "status": "success",
        "path": str(output_path),
        "format": "markdown",
        "size": output_path.stat().st_size
    }


def _generate_pdf_report(title: str, sections: List[Dict[str, Any]], output_path: Path) -> Dict[str, Any]:
    """Generate a PDF report using reportlab or markdown->PDF conversion."""
    
    # Try reportlab first
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        
        return _generate_pdf_with_reportlab(title, sections, output_path)
    
    except ImportError:
        # Fallback: generate markdown and suggest conversion
        md_path = output_path.with_suffix(".md")
        result = _generate_markdown(title, sections, md_path)
        
        if result.get("status") == "success":
            result["format"] = "markdown"
            result["message"] = (
                f"PDF generation requires reportlab. Generated Markdown instead at {md_path}. "
                "To enable PDF: pip install reportlab"
            )
        
        return result


def _generate_pdf_with_reportlab(title: str, sections: List[Dict[str, Any]], output_path: Path) -> Dict[str, Any]:
    """Generate PDF using reportlab library."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    
    # Create PDF document
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18
    )
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    # Title
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 0.2 * inch))
    
    # Timestamp
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    elements.append(Paragraph(f"<i>Generated: {timestamp}</i>", styles['Normal']))
    elements.append(Spacer(1, 0.3 * inch))
    
    # Sections
    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", "")
        section_type = section.get("type", "text")
        
        if heading:
            elements.append(Paragraph(heading, heading_style))
            elements.append(Spacer(1, 0.1 * inch))
        
        if section_type == "text":
            # Handle multi-line text
            for para in str(content).split('\n'):
                if para.strip():
                    elements.append(Paragraph(para, styles['Normal']))
                    elements.append(Spacer(1, 0.1 * inch))
        
        elif section_type == "table":
            # Build table data
            if isinstance(content, dict) and "headers" in content:
                headers = content["headers"]
                rows = content["rows"]
                table_data = [headers] + rows
            elif isinstance(content, list) and content:
                headers = list(content[0].keys())
                rows = [[str(row.get(h, "")) for h in headers] for row in content]
                table_data = [headers] + rows
            else:
                elements.append(Paragraph("<i>No table data</i>", styles['Normal']))
                elements.append(Spacer(1, 0.2 * inch))
                continue
            
            # Create table
            t = Table(table_data)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(t)
            elements.append(Spacer(1, 0.2 * inch))
        
        elif section_type == "list":
            items = content if isinstance(content, list) else [content]
            for item in items:
                elements.append(Paragraph(f"• {item}", styles['Normal']))
            elements.append(Spacer(1, 0.2 * inch))
        
        elif section_type == "code":
            code_style = ParagraphStyle(
                'Code',
                parent=styles['Code'],
                fontSize=9,
                leftIndent=20,
                rightIndent=20,
                spaceAfter=12
            )
            elements.append(Paragraph(f"<pre>{content}</pre>", code_style))
            elements.append(Spacer(1, 0.2 * inch))
        
        else:
            elements.append(Paragraph(str(content), styles['Normal']))
            elements.append(Spacer(1, 0.2 * inch))
    
    # Build PDF
    doc.build(elements)
    
    return {
        "status": "success",
        "path": str(output_path),
        "format": "pdf",
        "size": output_path.stat().st_size
    }
