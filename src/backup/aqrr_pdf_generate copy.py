# aqrr_pdf_generate.py
import os
import io
import json
import re
import requests
import numpy as np
import pandas as pd
from datetime import datetime
import argparse
import sys

# PDF generation imports
from fastapi import APIRouter, FastAPI, HTTPException, Body
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.platypus.flowables import KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Word document generation imports
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


router = APIRouter()
app = FastAPI(title="PDF API")
app.include_router(router, prefix="/pdf")


def draw_aqrr_header(canvas, doc):
    canvas.saveState()
    width, height = doc.pagesize
    # Header texts
    left_text = "PGIM Private Capital"
    center_text = "Annual Quality Rating Review"
    date_str = datetime.now().strftime("%m/%d/%Y")
    # Fonts and positions
    canvas.setFont("Helvetica-Bold", 12)
    y = height - 0.4 * inch
    canvas.drawString(doc.leftMargin, y, left_text)
    canvas.drawCentredString(width / 2, y, center_text)
    canvas.drawRightString(width - doc.rightMargin, y, date_str)
    
    # Add page number at the bottom right
    canvas.setFont("Helvetica", 9)
    page_num = canvas.getPageNumber()
    canvas.drawRightString(width - doc.rightMargin, 0.5 * inch, f"{page_num}")
    
    canvas.restoreState()


def get_company_title_from_ticker(ticker: str, mapping_path: str = os.path.join('static', 'company_ticker.json')) -> str:
    """Return company title/name for a given ticker using static/company_ticker.json.
    Falls back to ticker if not found or file missing.
    """
    try:
        with open(mapping_path, 'r') as f:
            mapping = json.load(f)
        t_upper = ticker.upper()
        for _, entry in mapping.items():
            if isinstance(entry, dict) and entry.get('ticker', '').upper() == t_upper:
                return entry.get('title') or t_upper
    except Exception:
        pass
    return ticker


def current_quarter_index(reference: datetime | None = None) -> int:
    ref = reference or datetime.now()
    m = ref.month
    if m <= 3:
        return 1
    if m <= 6:
        return 2
    if m <= 9:
        return 3
    return 4


def quarter_end_label_for_year(year: int, reference: datetime | None = None) -> str:
    """Return the quarter-end label like '3/31/25' based on the current quarter for the given year."""
    q = current_quarter_index(reference)
    md = [(3, 31), (6, 30), (9, 30), (12, 31)][q - 1]
    mm, dd = md
    yy = year % 100
    return f"{mm}/{dd}/{yy:02d}"


def format_number_for_display(val):
    """Format numbers for display in HFA table: remove 000s and format negatives with parentheses"""
    try:
        if val is None or val == "" or (isinstance(val, str) and val.strip() == "-"):
            return "-"
        
        # Handle percentage values differently
        if isinstance(val, str) and '%' in val:
            return val
            
        # Convert to float and divide by 1000 to remove 000s
        f = float(val) / 1000
        
        # Format negative numbers with parentheses
        if f < 0:
            # Remove the negative sign and wrap in parentheses
            if abs(f - int(f)) < 1e-6:  # Integer
                return f"({int(abs(f)):,})"
            else:  # Float with decimals
                return f"({abs(f):,.1f})"
        else:
            # Positive numbers
            if abs(f - int(f)) < 1e-6:  # Integer
                return f"{int(f):,}"
            else:  # Float with decimals
                return f"{f:,.1f}"
    except Exception:
        # If conversion fails, return as is
        return str(val)


def flatten_json(nested_json, prefix='', separator='_'):
    """
    Flatten a nested JSON structure into a flat dictionary.
    Improved to handle complex nested structures including lists of objects.
    """
    flattened = {}
    for key, value in nested_json.items():
        if isinstance(value, dict):
            flattened.update(flatten_json(value, f"{prefix}{key}{separator}", separator))
        elif isinstance(value, list):
            if value and all(isinstance(item, dict) for item in value):
                for i, item in enumerate(value):
                    flattened.update(flatten_json(item, f"{prefix}{key}{separator}{i}{separator}", separator))
            else:
                flattened[f"{prefix}{key}"] = json.dumps(value)
        else:
            flattened[f"{prefix}{key}"] = value
    return flattened


def json_to_dataframe(json_data):
    """
    Convert JSON data to a pandas DataFrame.
    Handles both array of objects and single object formats.
    Improved to better handle complex nested structures.
    """
    if isinstance(json_data, list):
        if not json_data:
            return pd.DataFrame()

        if all(isinstance(item, dict) for item in json_data):
            try:
                return pd.json_normalize(json_data)
            except Exception:
                flattened_data = [flatten_json(item) for item in json_data]
                return pd.DataFrame(flattened_data)
        else:
            return pd.DataFrame(json_data, columns=['Value'])
    elif isinstance(json_data, dict):
        try:
            return pd.json_normalize([json_data])
        except Exception:
            flattened_data = flatten_json(json_data)
            return pd.DataFrame([flattened_data])
    else:
        return pd.DataFrame([json_data], columns=['Value'])


@router.get('/get_companies')
def get_companies():
    """Dynamically lists company folders."""
    base_folder = os.getenv('COMPANY_DATA_FOLDER', 'company_data')
    try:
        companies = [
            d for d in os.listdir(base_folder)
            if os.path.isdir(os.path.join(base_folder, d))
        ]
        return companies
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Company data folder not found.")


@router.post('/aqrr_pdf')
def generate_pdf(data: dict = Body(...)):
    """Generates a PDF from company data."""
    company_name = data.get('company')
    if not company_name:
        raise HTTPException(status_code=400, detail="No company name provided.")

    base_folder = os.getenv('COMPANY_DATA_FOLDER', 'company_data')
    company_path = os.path.join(base_folder, company_name)
    if not os.path.exists(company_path):
        raise HTTPException(status_code=404, detail="Company folder not found.")

    # Find the data file (csv, excel, or json)
    data_file = None
    for filename in os.listdir(company_path):
        if filename.endswith(('.csv', '.xlsx', '.json')):
            data_file = os.path.join(company_path, filename)
            break

    if not data_file:
        raise HTTPException(status_code=404, detail="Data file (csv, xlsx, or json) not found.")

    # Load data from the file
    try:
        if data_file.endswith('.csv'):
            df = pd.read_csv(data_file)
            # Replace NaN values with empty strings for CSV files
            df = df.replace({np.nan: ''})
        elif data_file.endswith('.xlsx'):
            # Explicitly specify the sheet name
            df = pd.read_excel(data_file, sheet_name='Essence Table')
        elif data_file.endswith('.json'):
            with open(data_file, 'r') as f:
                json_data = json.load(f)
            df = json_to_dataframe(json_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading data file or worksheet: {e}")

    # Handle case where the data file or sheet is empty
    if df.empty:
        raise HTTPException(status_code=500, detail="Data file or specified worksheet is empty. Cannot create a table.")

    # Load statement analysis text
    analysis_file = os.path.join(company_path, 'statement_analysis.txt')
    if os.path.exists(analysis_file):
        with open(analysis_file, 'r') as f:
            analysis_text = f.read()
    else:
        analysis_text = "No statement analysis text found."

    # Generate the PDF
    buffer = io.BytesIO()

    # Set up document with adjusted margins for more horizontal space
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )
    elements = []
    styles = getSampleStyleSheet()

    # Define paragraph styles for table data
    styles.add(ParagraphStyle(
        name='TableDataFirstCol',
        fontSize=7,
        leading=8,
        alignment=0  # Left alignment for first column
    ))

    styles.add(ParagraphStyle(
        name='TableData',
        fontSize=7,
        leading=8,
        alignment=1  # Center alignment for other columns
    ))

    # Define styles for table headers
    styles.add(ParagraphStyle(
        name='TableHeaderFirstCol',
        fontSize=8,
        leading=9,
        alignment=0,  # Left alignment for first column header
        fontName='Helvetica-Bold',
        textColor=colors.whitesmoke
    ))

    styles.add(ParagraphStyle(
        name='TableHeader',
        fontSize=8,
        leading=9,
        alignment=1,  # Center alignment for other headers
        fontName='Helvetica-Bold',
        textColor=colors.whitesmoke
    ))


    # Special handling for CSV files to create a two-row header
    if data_file.endswith('.csv'):
        # Assuming the first two rows should be headers
        if len(df) >= 2:
            # Extract the first two rows for headers
            header_row1 = []
            header_row2 = []

            # Apply different styles to first column vs other columns in headers
            for i, cell in enumerate(df.columns.tolist()):
                style = styles['TableHeaderFirstCol'] if i == 0 else styles['TableHeader']
                header_row1.append(Paragraph(str(cell), style))

            for i, cell in enumerate(df.iloc[0].tolist()):
                style = styles['TableHeaderFirstCol'] if i == 0 else styles['TableHeader']
                header_row2.append(Paragraph(str(cell), style))

            # Remove the first row from the dataframe as it's now part of the header
            df = df.iloc[1:].reset_index(drop=True)

            # Prepare table data rows
            table_rows = []
            for row in df.values.tolist():
                formatted_row = []
                for i, cell in enumerate(row):
                    style = styles['TableDataFirstCol'] if i == 0 else styles['TableData']
                    formatted_row.append(Paragraph(str(cell) if cell != '' else '', style))
                table_rows.append(formatted_row)

            # Create table style with blue header background and no internal lines
            table_style = TableStyle([
                # Blue background for header rows
                ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#44546A')),
                ('TEXTCOLOR', (0, 0), (-1, 1), colors.whitesmoke),
                # First column left aligned for ALL rows (including headers and data)
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                # Other columns center aligned
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
                # Reduce padding to make header rows closer together
                ('BOTTOMPADDING', (0, 0), (-1, 1), 0),
                ('TOPPADDING', (0, 0), (-1, 1), 3),
                # White background for data rows
                ('BACKGROUND', (0, 2), (-1, -1), colors.white),
                # Only draw the outer border of the table
                ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
                # Add horizontal line between header and data
                ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.black),
                # Minimal padding for all cells to ensure compact layout
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                # Tighten data rows
                ('BOTTOMPADDING', (0, 2), (-1, -1), 1.5),
                ('TOPPADDING', (0, 2), (-1, -1), 1.5),
            ])
            # Define the exact keywords to check for
            exact_keywords = ["Total Debt", "Total Debt + COLs", "Book Capitalization", "Market Capitalization"]
            for i, row in enumerate(table_rows):
                first_cell_value = str(df.iloc[i, 0]) if len(df.columns) > 0 else ""
                # Check if the cell value exactly matches any of the keywords
                if first_cell_value in exact_keywords:
                    # Add line above this row
                    table_style.add('LINEABOVE', (0, i + 2), (-1, i + 2), 0.5, colors.black)
                    # Make the entire row bold
                    for j in range(len(row)):
                        cell_text = row[j].text
                        row[j] = Paragraph(f"<b>{cell_text}</b>", styles['TableData'])
                    # Add indent to first column
                    if row and isinstance(row[0], Paragraph):
                        row[0] = Paragraph(f"<b>&nbsp;&nbsp;&nbsp;{first_cell_value}</b>", styles['TableDataFirstCol'])

                # Special handling for "Key Financial Ratios:"
                elif first_cell_value == "Key Financial Ratios:":
                    # Add line above and below this row
                    table_style.add('LINEABOVE', (0, i + 2), (-1, i + 2), 0.5, colors.black)
                    table_style.add('LINEBELOW', (0, i + 2), (-1, i + 2), 0.5, colors.black)
                    # Add grey background
                    table_style.add('BACKGROUND', (0, i + 2), (-1, i + 2), colors.lightgrey)

                    # Span the cell across all columns to center the text
                    num_cols = len(df.columns)
                    if num_cols > 1:
                        table_style.add('SPAN', (0, i + 2), (num_cols - 1, i + 2))

                    # Make the text bold and centered
                    bold_italic_text = f"<b><i>{first_cell_value}</i></b>"
                    row[0] = Paragraph(bold_italic_text, ParagraphStyle(
                        name='CenteredHeader',
                        parent=styles['TableData'],
                        alignment=1,  # Center alignment
                        fontSize=8,
                    ))

                    # Remove other cells in this row since we're spanning
                    for j in range(1, len(row)):
                        row[j] = Paragraph("", styles['TableData'])


            data = [header_row1, header_row2] + table_rows

            # Calculate column widths to fit the page - first column gets 45% of 60% width
            available_width = doc.width * 0.6
            num_cols = len(df.columns)
            if num_cols > 0:
                first_col_width = available_width * 0.45
                remaining_width = available_width * 0.55
                if num_cols > 1:
                    col_widths = [first_col_width] + [remaining_width / (num_cols - 1) for _ in range(num_cols - 1)]
                else:
                    col_widths = [available_width]
            else:
                col_widths = []

        else:
            # If there aren't enough rows for a two-row header, use a single row header
            table_headers = [Paragraph(str(col), styles['TableHeader']) for col in df.columns.tolist()]
            table_rows = []
            for row in df.values.tolist():
                table_rows.append([Paragraph(str(cell) if cell != '' else '', styles['TableData']) for cell in row])

            # Define default table style for single-row header CSV case
            table_style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#44546A')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
                ('TOPPADDING', (0, 0), (-1, 0), 3),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ])

            data = [table_headers] + table_rows

            # Calculate column widths to fit the page - first column gets 30% of width
            available_width = doc.width
            num_cols = len(df.columns)
            if num_cols > 0:
                first_col_width = available_width * 0.3
                remaining_width = available_width * 0.7
                if num_cols > 1:
                    col_widths = [first_col_width] + [remaining_width / (num_cols - 1) for _ in range(num_cols - 1)]
                else:
                    col_widths = [available_width]
            else:
                col_widths = []

    else:
        # Original handling for non-CSV files
        table_headers = [Paragraph(str(col), styles['TableHeader']) for col in df.columns.tolist()]
        table_rows = []
        for row in df.values.tolist():
            table_rows.append([Paragraph(str(cell), styles['TableData']) for cell in row])

        # Initialize table_style BEFORE adding dynamic rules
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#44546A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            # First column left aligned for ALL rows
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            # Other columns center aligned
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
            ('TOPPADDING', (0, 0), (-1, 0), 3),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ])

        # Styling based on first column content
        for i, row in enumerate(table_rows):
            first_cell_value = str(df.iloc[i, 0]) if len(df.columns) > 0 else ""
            if any(keyword in first_cell_value for keyword in ["Total Debt", "Book Capitalization", "Market Capitalization"]):
                # Add line above this row
                table_style.add('LINEABOVE', (0, i + 1), (-1, i + 1), 0.5, colors.black)
                # Make the entire row bold
                for j in range(len(row)):
                    cell_text = row[j].text
                    row[j] = Paragraph(f"<b>{cell_text}</b>", styles['TableData'])
                # Add indent to first column
                if row and isinstance(row[0], Paragraph):
                    row[0] = Paragraph(f"<b>&nbsp;&nbsp;&nbsp;{first_cell_value}</b>", styles['TableData'])

        data = [table_headers] + table_rows

        # Calculate column widths to fit the page.
        available_width = doc.width
        num_cols = len(df.columns)
        if num_cols > 0:
            if num_cols > 1:
                col_widths = [available_width * 0.2] + [available_width * 0.8 / (num_cols - 1) for _ in range(num_cols - 1)]
            else:
                col_widths = [available_width]
        else:
            col_widths = []

    table = Table(data, colWidths=col_widths)
    table.setStyle(table_style)

    elements.append(KeepTogether(table))
    elements.append(Spacer(1, 24))

    # Add text from statement analysis
    for line in analysis_text.split('\n'):
        elements.append(Paragraph(line, styles['Normal']))

    doc.build(elements, onFirstPage=draw_aqrr_header, onLaterPages=draw_aqrr_header)
    buffer.seek(0)

    headers = {"Content-Disposition": f"attachment; filename={company_name}_report.pdf"}
    return StreamingResponse(buffer, media_type='application/pdf', headers=headers)

def build_pdf_bytes_from_ticker(ticker: str,
                                hfa_dir: str = os.path.join('output', 'json', 'hfa_output'),
                                fsa_dir: str = os.path.join('output', 'json', 'financial_analysis')) -> bytes:
    """
    Build the PDF for a given ticker by calling the HFA API and using its rows:
    - HFA table data from: POST {BASE_URL}/api/v1/hfa with body {"ticker": TICKER}
      BASE_URL is taken from env APP_BASE_URL (default http://127.0.0.1:3030)
    - Financial Statement Analysis from: output/json/financial_analysis/{TICKER}_FSA.json

    Returns raw PDF bytes.
    """
    if not ticker:
        raise ValueError("No ticker provided.")

    # Resolve FSA input JSON path
    fsa_path = os.path.join(fsa_dir, f"{ticker}_FSA.json")

    # Call HFA API to get rows for the table
    api_base = os.getenv('APP_BASE_URL', 'http://127.0.0.1:3030')
    api_url = f"{api_base.rstrip('/')}/api/v1/hfa"
    try:
        resp = requests.post(api_url, json={"ticker": ticker}, timeout=300)
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to call HFA API at {api_url}: {e}")
    if resp.status_code != 200:
        try:
            err_detail = resp.json()
        except Exception:
            err_detail = resp.text
        raise RuntimeError(f"HFA API returned {resp.status_code}: {err_detail}")
    try:
        payload = resp.json()
    except Exception as e:
        raise RuntimeError(f"Invalid JSON from HFA API: {e}")

    hfa_rows = payload.get("rows")
    if not isinstance(hfa_rows, list) or not hfa_rows:
        raise RuntimeError("HFA API response missing 'rows' list with data")

    # Convert HFA rows to DataFrame
    df = json_to_dataframe(hfa_rows)
    # Clean NaNs for rendering
    df = df.replace({np.nan: ''})
    
    # Format the numbers: remove 000s (divide by 1000) and format negative numbers with parentheses
    for col in df.columns:
        if col != 'Metric':
            df[col] = df[col].apply(lambda x: format_number_for_display(x) if x != '' else '')
            
    # Special formatting for percentage rows
    for i, row in enumerate(df.values):
        metric = str(row[0]) if row[0] != '' else ''
        if metric in ['% YoY Growth', '% Margin']:
            for j, val in enumerate(row):
                if j > 0 and val not in ['', '-']:
                    try:
                        # Format as percentage with one decimal place
                        num_val = float(val.replace('(', '-').replace(')', '').replace(',', '')) if isinstance(val, str) else float(val)
                        if num_val < 0:
                            df.iloc[i, j] = f'({abs(num_val):.1f}%)'
                        else:
                            df.iloc[i, j] = f'{num_val:.1f}%'
                    except:
                        # Keep as is if conversion fails
                        pass
    # Ensure 'Metric' is the first column if present
    if 'Metric' in df.columns:
        cols = df.columns.tolist()
        cols.remove('Metric')
        df = df[['Metric'] + cols]

    # Reorder columns into: Metric | years (asc) | YTD years (asc) | LTM years (asc)
    # Also capture groups to construct a two-row header later
    all_cols = df.columns.tolist()
    year_cols = [c for c in all_cols if isinstance(c, str) and c.isdigit() and len(c) == 4]
    try:
        year_cols_sorted = sorted(year_cols, key=lambda x: int(x))
    except Exception:
        year_cols_sorted = year_cols

    ytd_cols = [c for c in all_cols if isinstance(c, str) and c.startswith('YTD ')]
    try:
        ytd_cols_sorted = sorted(ytd_cols, key=lambda x: int(x.split()[1]))
    except Exception:
        ytd_cols_sorted = ytd_cols

    ltm_cols = [c for c in all_cols if isinstance(c, str) and c.startswith('LTM ')]
    try:
        ltm_cols_sorted = sorted(ltm_cols, key=lambda x: int(x.split()[1]))
    except Exception:
        ltm_cols_sorted = ltm_cols

    ordered_cols = ['Metric']
    ordered_cols += [c for c in year_cols_sorted if c in all_cols]
    ordered_cols += [c for c in ytd_cols_sorted if c in all_cols]
    ordered_cols += [c for c in ltm_cols_sorted if c in all_cols]
    # Only reorder if all expected columns present
    if all(c in all_cols for c in ordered_cols) and len(ordered_cols) == len(all_cols):
        df = df[ordered_cols]

    # Fetch CAP table JSON and COMP rows from APIs (non-fatal if unavailable)
    cap_json = None
    comp_rows = None
    try:
        cap_url = f"{api_base.rstrip('/')}/api/v1/cap-table"
        cap_resp = requests.post(cap_url, json={"ticker": ticker}, timeout=300)
        if cap_resp.status_code == 200:
            try:
                cap_payload = cap_resp.json()
                if isinstance(cap_payload, dict):
                    cap_json = cap_payload.get("json_data")
                    # Fallback: parse raw JSON string if provided by API
                    if cap_json is None and isinstance(cap_payload.get("json_data_raw"), str):
                        raw = cap_payload.get("json_data_raw")
                        def _try_parse_json_text(s: str):
                            try:
                                return json.loads(s)
                            except Exception:
                                # sanitize and retry: remove trailing commas and trim to outer braces
                                s2 = s.strip()
                                if s2.startswith("```"):
                                    s2 = s2.strip('`')
                                s2 = re.sub(r",\s*([}\]])", r"\1", s2)
                                if '{' in s2 and '}' in s2:
                                    s2 = s2[s2.find('{'): s2.rfind('}') + 1]
                                try:
                                    return json.loads(s2)
                                except Exception:
                                    return None
                        cap_json = _try_parse_json_text(raw)
            except Exception:
                cap_json = None
    except Exception:
        cap_json = None

    try:
        comp_url = f"{api_base.rstrip('/')}/api/v1/comp"
        comp_resp = requests.post(comp_url, json={"ticker": ticker}, timeout=300)
        if comp_resp.status_code == 200:
            try:
                comp_payload = comp_resp.json()
                if isinstance(comp_payload, dict):
                    comp_rows = comp_payload.get("rows")
            except Exception:
                comp_rows = None
    except Exception:
        comp_rows = None

    # Load FSA data if available
    fsa_data = None
    if os.path.exists(fsa_path):
        with open(fsa_path, 'r') as f:
            try:
                fsa_data = json.load(f)
            except Exception:
                fsa_data = None

    # Generate the PDF in-memory
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )
    elements = []
    styles = getSampleStyleSheet()

    # Define paragraph styles for table data
    styles.add(ParagraphStyle(
        name='TableDataFirstCol',
        fontSize=7,
        leading=8,
        alignment=0  # Left alignment for first column
    ))

    styles.add(ParagraphStyle(
        name='TableData',
        fontSize=7,
        leading=8,
        alignment=1  # Center alignment for other columns
    ))

    # Define styles for table headers
    styles.add(ParagraphStyle(
        name='TableHeaderFirstCol',
        fontSize=8,
        leading=9,
        alignment=0,  # Left alignment for first column header
        fontName='Helvetica-Bold',
        textColor=colors.whitesmoke
    ))

    styles.add(ParagraphStyle(
        name='TableHeader',
        fontSize=8,
        leading=9,
        alignment=1,  # Center alignment for other headers
        fontName='Helvetica-Bold',
        textColor=colors.whitesmoke
    ))

    # Build CAP table (above HFA) if available
    company_title = get_company_title_from_ticker(ticker)

    def _fmt_num(val):
        try:
            if val is None or val == "" or (isinstance(val, str) and val.strip() == "-"):
                return "-"
            # keep integers without decimals; floats with 2 decimals
            f = float(val)
            if abs(f - int(f)) < 1e-6:
                return f"{int(f):,}"
            return f"{f:,.2f}"
        except Exception:
            return str(val)

    if isinstance(cap_json, dict):
        # Prepare two-row header then a unified table with 6 columns
        cap_columns = ["Item", "Amount", "PPC Holdings", "Coupon", "Secured", "Maturity"]

        header_row1_cap = [Paragraph(f"{company_title} - Capitalization Table", styles['TableHeaderFirstCol'])]
        header_row1_cap += [Paragraph("", styles['TableHeader']) for _ in range(len(cap_columns) - 1)]

        header_row2_cap = []
        for i, col in enumerate(cap_columns):
            style = styles['TableHeaderFirstCol'] if i == 0 else styles['TableHeader']
            header_row2_cap.append(Paragraph(col, style))

        cap_table_rows = []
        # As-of line (spans all columns)
        as_of = cap_json.get('as_of') or ""
        asof_text = f"As of {as_of}" if as_of else ""
        asof_row = [Paragraph(asof_text, styles['TableDataFirstCol'])] + [Paragraph("", styles['TableData']) for _ in range(len(cap_columns) - 1)]
        cap_table_rows.append(asof_row)

        # Cash and Equivalents
        cae = cap_json.get('cash_and_equivalents')
        cap_table_rows.append([
            Paragraph("Cash and Equivalents", styles['TableDataFirstCol']),
            Paragraph(_fmt_num(cae), styles['TableData']),
            Paragraph("", styles['TableData']),
            Paragraph("", styles['TableData']),
            Paragraph("", styles['TableData']),
            Paragraph("", styles['TableData']),
        ])

        # Debt breakdown
        debt_list = cap_json.get('debt') or []
        for d in debt_list:
            if not isinstance(d, dict):
                continue
            cap_table_rows.append([
                Paragraph(str(d.get('type', '')), styles['TableDataFirstCol']),
                Paragraph(_fmt_num(d.get('amount')), styles['TableData']),
                Paragraph(str(d.get('ppc_holdings', '')), styles['TableData']),
                Paragraph(str(d.get('coupon', '')), styles['TableData']),
                Paragraph(str(d.get('secured', '')), styles['TableData']),
                Paragraph(str(d.get('maturity', '')), styles['TableData']),
            ])

        # Totals and other summary items
        def _append_summary_row(label_key: str, display: str | None = None):
            label = display or label_key.replace('_', ' ').title()
            val = cap_json.get(label_key)
            cap_table_rows.append([
                Paragraph(label, styles['TableDataFirstCol']),
                Paragraph(_fmt_num(val), styles['TableData']),
                Paragraph("", styles['TableData']),
                Paragraph("", styles['TableData']),
                Paragraph("", styles['TableData']),
                Paragraph("", styles['TableData']),
            ])

        # Add important totals in a specific order
        for key, disp in [
            ("total_debt", "Total Debt"),
            ("book_value_of_equity", "Book Value of Equity"),
            ("book_capitalization", "Book Capitalization"),
            ("market_value_of_equity", "Market Value of Equity"),
            ("market_capitalization", "Market Capitalization"),
            ("ltm_adj_ebitda", "LTM Adjusted EBITDA"),
            ("market_value_of_re_assets", "Market Value of RE Assets"),
            ("unencumbered_assets", "Unencumbered Assets"),
        ]:
            _append_summary_row(key, disp)

        # Key financial ratios header (spans all columns)
        kfr = cap_json.get('key_financial_ratios') or {}
        if isinstance(kfr, dict) and kfr:
            cap_table_rows.append([
                Paragraph("Key Financial Ratios:", ParagraphStyle(
                    name='CenteredHeaderCap', parent=styles['TableData'], alignment=1, fontSize=8
                )),
                Paragraph("", styles['TableData']),
                Paragraph("", styles['TableData']),
                Paragraph("", styles['TableData']),
                Paragraph("", styles['TableData']),
                Paragraph("", styles['TableData']),
            ])
            for k, v in kfr.items():
                label = k.replace('_', ' ').title() if isinstance(k, str) else str(k)
                cap_table_rows.append([
                    Paragraph(label, styles['TableDataFirstCol']),
                    Paragraph(str(v), styles['TableData']),
                    Paragraph("", styles['TableData']),
                    Paragraph("", styles['TableData']),
                    Paragraph("", styles['TableData']),
                    Paragraph("", styles['TableData']),
                ])

        data_cap = [header_row1_cap, header_row2_cap] + cap_table_rows

        available_width_cap = doc.width
        first_col_w_cap = available_width_cap * 0.35
        rem_w_cap = available_width_cap - first_col_w_cap
        per_w = rem_w_cap / (len(cap_columns) - 1) if len(cap_columns) > 1 else available_width_cap
        col_widths_cap = [first_col_w_cap] + [per_w for _ in range(len(cap_columns) - 1)]

        cap_style = TableStyle([
            ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#44546A')),
            ('TEXTCOLOR', (0, 0), (-1, 1), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 1), 0),
            ('TOPPADDING', (0, 0), (-1, 1), 3),
            ('BACKGROUND', (0, 2), (-1, -1), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
            ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ])

        # Add dynamic styling for notable rows and the ratios header
        base_row = 2  # account for two header rows
        for i, row in enumerate(cap_table_rows):
            abs_row = base_row + i
            first_val = ''
            try:
                first_val = row[0].text
            except Exception:
                first_val = ''
            if first_val in ("Total Debt", "Book Capitalization", "Market Capitalization"):
                cap_style.add('LINEABOVE', (0, abs_row), (-1, abs_row), 0.5, colors.black)
                # Bold the entire row
                for j in range(len(row)):
                    try:
                        cell_text = row[j].text
                        row[j] = Paragraph(f"<b>{cell_text}</b>", styles['TableData'])
                    except Exception:
                        pass
            elif first_val.strip().lower().startswith("key financial ratios"):
                cap_style.add('SPAN', (0, abs_row), (-1, abs_row))
                cap_style.add('BACKGROUND', (0, abs_row), (-1, abs_row), colors.lightgrey)
                cap_style.add('LINEABOVE', (0, abs_row), (-1, abs_row), 0.5, colors.black)
                cap_style.add('LINEBELOW', (0, abs_row), (-1, abs_row), 0.5, colors.black)

        cap_table = Table(data_cap, colWidths=col_widths_cap)
        cap_table.setStyle(cap_style)
        elements.append(KeepTogether(cap_table))
        elements.append(Spacer(1, 24))

    # Build table from HFA DataFrame with custom two-row header
    columns = df.columns.tolist()
    # Determine groups again from ordered columns
    year_cols = [c for c in columns if isinstance(c, str) and c.isdigit() and len(c) == 4]
    ytd_cols = [c for c in columns if isinstance(c, str) and c.startswith('YTD ')]
    ltm_cols = [c for c in columns if isinstance(c, str) and c.startswith('LTM ')]

    years_count = len(year_cols)
    ytd_count = len(ytd_cols)
    ltm_count = len(ltm_cols)

    left_top = f"{company_title} - Historical Financial Analysis"
    fye_str = "12/31"  # Default fiscal year end if unknown

    # Row 1 header
    header_row1 = []
    header_row1.append(Paragraph(left_top, styles['TableHeaderFirstCol']))
    # Fill placeholders for remaining columns
    for _ in range(years_count + ytd_count + ltm_count):
        header_row1.append(Paragraph("", styles['TableHeader']))

    # Place group titles
    if years_count > 0:
        header_row1[1] = Paragraph("Fiscal Year Ended", styles['TableHeader'])
    if ytd_count > 0:
        header_row1[1 + years_count] = Paragraph("YTD", styles['TableHeader'])
    if ltm_count > 0:
        header_row1[1 + years_count + ytd_count] = Paragraph("LTM", styles['TableHeader'])

    # Row 2 header
    header_row2 = []
    header_row2.append(Paragraph(f"<i>(FYE {fye_str})</i>", styles['TableHeaderFirstCol']))
    # Years
    for y in year_cols:
        header_row2.append(Paragraph(str(y), styles['TableHeader']))
    # YTD dates
    for ytd in ytd_cols:
        try:
            yr = int(str(ytd).split()[1])
            header_row2.append(Paragraph(quarter_end_label_for_year(yr), styles['TableHeader']))
        except Exception:
            header_row2.append(Paragraph(str(ytd), styles['TableHeader']))
    # LTM dates
    for ltm in ltm_cols:
        try:
            yr = int(str(ltm).split()[1])
            header_row2.append(Paragraph(quarter_end_label_for_year(yr), styles['TableHeader']))
        except Exception:
            header_row2.append(Paragraph(str(ltm), styles['TableHeader']))

    # Data rows
    table_rows = []
    for i, row in enumerate(df.values.tolist()):
        formatted_row = []
        # Get the metric name (first column)
        metric_name = str(row[0]) if row[0] != '' else ''
        
        # Determine if this row should be indented
        indent_metrics = ['% YoY Growth', '% Margin', 'Other']
        needs_indent = any(metric_name == m for m in indent_metrics)
        
        # Determine if this row should be bold
        bold_metrics = ['Revenue', 'Gross Profit', 'Adjusted EBITDA', 'Free Cash Flow', 
                       'Total Debt', 'Book Equity', 'Change in Cash', 'Cash - End of Period']
        needs_bold = any(metric_name == m for m in bold_metrics)
        
        # Format first column with indentation if needed
        if needs_indent:
            first_cell = f"&nbsp;&nbsp;&nbsp;{metric_name}"
        else:
            first_cell = metric_name
            
        # Apply bold formatting if needed
        if needs_bold:
            first_cell = f"<b>{first_cell}</b>"
            formatted_row.append(Paragraph(first_cell, styles['TableDataFirstCol']))
            # Make all cells in this row bold
            for j, cell in enumerate(row[1:], 1):
                cell_text = str(cell) if cell != '' else ''
                if cell_text:
                    formatted_row.append(Paragraph(f"<b>{cell_text}</b>", styles['TableData']))
                else:
                    formatted_row.append(Paragraph('', styles['TableData']))
        else:
            # Regular formatting
            formatted_row.append(Paragraph(first_cell, styles['TableDataFirstCol']))
            for j, cell in enumerate(row[1:], 1):
                cell_text = str(cell) if cell != '' else ''
                formatted_row.append(Paragraph(cell_text, styles['TableData']))
                
        table_rows.append(formatted_row)

    table_style = TableStyle([
        # Blue background over first two header rows
        ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#44546A')),
        ('TEXTCOLOR', (0, 0), (-1, 1), colors.whitesmoke),
        # Alignments
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        # Header font
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 1), 0),
        ('TOPPADDING', (0, 0), (-1, 1), 3),
        # White background for data rows
        ('BACKGROUND', (0, 2), (-1, -1), colors.white),
        # Outer border
        ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
        # Line below the two-row header
        ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.black),
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ])

    # Add spans for groupings
    # Years span across columns 1..years_count
    if years_count > 0:
        table_style.add('SPAN', (1, 0), (years_count, 0))
    # YTD span across next ytd_count
    if ytd_count > 0:
        ytd_start = 1 + years_count
        ytd_end = ytd_start + ytd_count - 1
        table_style.add('SPAN', (ytd_start, 0), (ytd_end, 0))
    # LTM span across next ltm_count (likely 1)
    if ltm_count > 0:
        ltm_start = 1 + years_count + ytd_count
        ltm_end = ltm_start + ltm_count - 1
        table_style.add('SPAN', (ltm_start, 0), (ltm_end, 0))

    # Add horizontal lines and special formatting
    for i, row in enumerate(table_rows):
        if i < len(df):
            first_cell_value = str(df.iloc[i, 0]) if len(df.columns) > 0 else ""
            
            # Add horizontal lines above specific rows
            if first_cell_value in ["Revenue", "Gross Profit", "Operating Expenses", "Adjusted EBITDA", 
                                   "Interest Expense", "Capital Expenditures", "Free Cash Flow", 
                                   "Acq. / Disp.", "Equity / Dividends", "Change in Cash", 
                                   "Cash - End of Period", "Total Debt", "Book Equity"]:
                table_style.add('LINEABOVE', (0, i + 2), (-1, i + 2), 0.5, colors.black)
                
            # Add Key Financial Ratios section
            if first_cell_value == "EBITDA / Int. Exp.":
                # Insert a Key Financial Ratios header row before this row
                kfr_row = [Paragraph("<b><i>Key Financial Ratios:</i></b>", ParagraphStyle(
                    name='CenteredHeader',
                    parent=styles['TableData'],
                    alignment=1,  # Center alignment
                    fontSize=8,
                ))]
                
                # Add empty cells for the rest of the columns
                for _ in range(len(df.columns) - 1):
                    kfr_row.append(Paragraph("", styles['TableData']))
                    
                # Insert the row at the current position
                table_rows.insert(i, kfr_row)
                
                # Add styling for the Key Financial Ratios row
                table_style.add('SPAN', (0, i + 2), (-1, i + 2))
                table_style.add('BACKGROUND', (0, i + 2), (-1, i + 2), colors.lightgrey)
                table_style.add('LINEABOVE', (0, i + 2), (-1, i + 2), 0.5, colors.black)
                table_style.add('LINEBELOW', (0, i + 2), (-1, i + 2), 0.5, colors.black)
                
                # Format all financial ratio rows to have x.x format
                for j in range(len(df)):
                    metric = str(df.iloc[j, 0]) if j < len(df) else ""
                    if any(ratio in metric for ratio in ["EBITDA / Int", "Debt / EBITDA", "Debt / Book", "EBITDAR / Interest"]):
                        # Format each column value as a ratio with x.x format
                        for col in range(1, len(df.columns)):
                            # Adjust row position in table_rows (add 2 for header rows, add 1 more if after inserted KFR row)
                            row_pos = j + 2 + (1 if j >= i else 0)
                            if row_pos < len(table_rows):
                                try:
                                    cell = table_rows[row_pos][col]
                                    if hasattr(cell, 'text') and cell.text and cell.text != '-':
                                        # Try to convert to float and format as x.x
                                        val = float(cell.text.replace('(', '-').replace(')', '').replace(',', ''))
                                        if val < 0:
                                            formatted = f"({abs(val):.1f}x)"
                                        else:
                                            formatted = f"{val:.1f}x"
                                        table_rows[row_pos][col] = Paragraph(formatted, styles['TableData'])
                                except Exception:
                                    pass  # Skip if conversion fails
                
                # Add horizontal lines above specific ratio rows
                for j in range(len(df)):
                    metric = str(df.iloc[j, 0]) if j < len(df) else ""
                    if metric in ["Total Debt / EBITDA", "Total Debt / Book Capital"]:
                        # Adjust row position (add 2 for header rows, add 1 more if after inserted KFR row)
                        row_pos = j + 2 + (1 if j >= i else 0)
                        table_style.add('LINEABOVE', (0, row_pos), (-1, row_pos), 0.5, colors.black)

    data = [header_row1, header_row2] + table_rows

    # Column widths (first column ~30%, remaining share ~70%)
    available_width = doc.width
    num_cols = len(df.columns)
    if num_cols > 0:
        if num_cols > 1:
            first_col_width = available_width * 0.30
            remaining_width = available_width * 0.70
            col_widths = [first_col_width] + [remaining_width / (num_cols - 1) for _ in range(num_cols - 1)]
        else:
            col_widths = [available_width]
    else:
        col_widths = []

    table = Table(data, colWidths=col_widths)
    table.setStyle(table_style)

    elements.append(KeepTogether(table))
    elements.append(Spacer(1, 24))

    # Add Financial Statement Analysis from JSON (if present)
    elements.append(Spacer(1, 12))

    # Define custom styles for FSA section
    section_header_style = ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=colors.darkslategray,
        underline=0,
        spaceAfter=6
    )
    
    bullet_style = ParagraphStyle(
        name='BulletPoint',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,  # Increased leading for better spacing between lines
        leftIndent=20,  # Indentation for the bullet points
        firstLineIndent=-12,  # Negative first line indent to make the bullet hang
        spaceBefore=4,
        spaceAfter=6,
        alignment=0  # Left alignment
    )

    if isinstance(fsa_data, dict):
        preferred_order = ["Income Statement", "Cash Flow Statement", "Balance Sheet"]
        for section in preferred_order + [k for k in fsa_data.keys() if k not in preferred_order]:
            if section in fsa_data and isinstance(fsa_data[section], list) and fsa_data[section]:
                # Add section header with underline
                elements.append(Paragraph(f"<u>{section}</u>", section_header_style))
                elements.append(Spacer(1, 6))
                
                # Add bullet points with proper formatting
                for point in fsa_data[section]:
                    elements.append(Paragraph(f"• {point}", bullet_style))
                
                elements.append(Spacer(1, 12))
    else:
        elements.append(Paragraph("No statement analysis data found for this ticker.", styles['Normal']))

    # Build COMP table (after FSA) if available
    if isinstance(comp_rows, list) and comp_rows:
        try:
            # Add a title for the Comparables Analysis section
            comp_title_style = ParagraphStyle(
                name='CompTitle',
                parent=styles['Heading2'],
                fontName='Helvetica-Bold',
                fontSize=11,
                leading=13,
                textColor=colors.black,
                spaceAfter=6
            )
            elements.append(Paragraph("Comparables Analysis:", comp_title_style))
            elements.append(Spacer(1, 6))
            
            df_comp = json_to_dataframe(comp_rows)
            df_comp = df_comp.replace({np.nan: '-'})  # Replace NaN with dash for better display
            
            # Limit the number of columns to match the screenshot (12 columns total including Ticker)
            max_columns = 12
            if len(df_comp.columns) > max_columns:
                df_comp = df_comp.iloc[:, :max_columns]
                
            comp_cols = df_comp.columns.tolist()

            # Define custom styles for the COMP table with smaller font sizes
            comp_header_style = ParagraphStyle(
                name='CompHeaderStyle',
                parent=styles['TableHeader'],
                fontSize=7.5,  # Increased font size
                leading=9,
                alignment=1,  # Center alignment
                textColor=colors.whitesmoke
            )
            
            comp_header_first_col_style = ParagraphStyle(
                name='CompHeaderFirstColStyle',
                parent=styles['TableHeaderFirstCol'],
                fontSize=7.5,  # Increased font size
                leading=9,
                alignment=0,  # Left alignment
                textColor=colors.whitesmoke
            )
            
            comp_data_style = ParagraphStyle(
                name='CompDataStyle',
                parent=styles['TableData'],
                fontSize=7,  # Increased font size
                leading=9,
                alignment=1  # Center alignment
            )
            
            comp_data_first_col_style = ParagraphStyle(
                name='CompDataFirstColStyle',
                parent=styles['TableDataFirstCol'],
                fontSize=7,  # Increased font size
                leading=9,
                alignment=0  # Left alignment
            )
            
            # Create header rows with proper styling
            # First header row (company name - Credit Comparable Analysis)
            header_row1_comp = [Paragraph(f"{company_title} - Credit Comparable Analysis", 
                                         ParagraphStyle(
                                             name='CompHeaderTitle',
                                             parent=comp_header_style,
                                             fontSize=7.5,  # Slightly larger for title
                                             alignment=1,  # Center alignment
                                             textColor=colors.whitesmoke
                                         ))]
            
            # Add empty cells for the rest of the columns in first header row
            for _ in range(len(comp_cols) - 1):
                header_row1_comp.append(Paragraph("", comp_header_style))

            # Second header row (LTM, 3-Year Average, etc.)
            # Define groups for the columns based on the screenshot
            col_groups = [
                ("LTM", 7),  # LTM spans 7 columns
                ("3-Year Average", 4)  # 3-Year Average spans 4 columns
            ]
            
            # Create second header row with column groups
            header_row2_comp = [Paragraph("", comp_header_first_col_style)]  # First cell empty
            
            # Add column group headers
            for group_name, span in col_groups:
                header_row2_comp.append(Paragraph(group_name, 
                                                ParagraphStyle(
                                                    name='CompHeaderGroup',
                                                    parent=comp_header_style,
                                                    alignment=1,  # Center alignment
                                                    textColor=colors.whitesmoke
                                                )))
                # Add empty cells for the span
                for _ in range(span - 1):
                    header_row2_comp.append(Paragraph("", comp_header_style))

            # Third header row (actual column names)
            header_row3_comp = []
            for i, col in enumerate(comp_cols):
                style = comp_header_first_col_style if i == 0 else comp_header_style
                # Shorten and format column names for better readability
                col_text = str(col)
                if i > 0:  # Skip first column (Ticker)
                    # Create more readable abbreviations
                    col_text = col_text.replace('Total', 'Tot')
                    col_text = col_text.replace('EBITDAR', 'EBTDAR')
                    col_text = col_text.replace('EBITDA', 'EBTDA')
                    col_text = col_text.replace('Margin', 'Mrgn')
                    col_text = col_text.replace('Revenue', 'Rev')
                    col_text = col_text.replace('Average', 'Avg')
                    
                    # Add line breaks for complex headers to improve readability
                    if '/' in col_text:
                        parts = col_text.split('/')
                        if len(parts) == 2:
                            col_text = f"{parts[0].strip()}<br/>{parts[1].strip()}"
                    
                    # Add line breaks for headers with parentheses
                    if '(' in col_text and ')' in col_text:
                        col_text = col_text.replace('(', '<br/>(').replace(')', ')')
                
                header_row3_comp.append(Paragraph(col_text, style))

            # Format the data rows
            comp_table_rows = []
            for row in df_comp.values.tolist():
                formatted_row = []
                for i, cell in enumerate(row):
                    cell_text = str(cell) if cell != '' else '-'
                    
                    # Format numbers with proper decimal places and x suffix for ratios
                    if i > 0 and cell_text != '-':  # Skip first column and empty cells
                        try:
                            val = float(str(cell_text).replace(',', ''))
                            # Format as ratio with x suffix if appropriate
                            if 'Ratio' in comp_cols[i] or any(x in comp_cols[i] for x in ['/', 'x']):
                                cell_text = f"{val:.1f}x"
                            # Format as percentage if appropriate
                            elif '%' in comp_cols[i] or 'Margin' in comp_cols[i]:
                                cell_text = f"{val:.1f}%"
                            # Format as regular number with 1 decimal place
                            else:
                                cell_text = f"{val:.1f}"
                        except (ValueError, TypeError):
                            pass  # Keep as is if not a number
                    
                    # Use appropriate style based on column
                    if i == 0:  # First column (company names)
                        # Italicize the company name if it's not Average or Median
                        if cell_text.upper() not in ("AVERAGE", "MEDIAN"):
                            cell_text = f"<i>{cell_text}</i>"
                        formatted_row.append(Paragraph(cell_text, comp_data_first_col_style))
                    else:  # Data columns
                        formatted_row.append(Paragraph(cell_text, comp_data_style))
                        
                comp_table_rows.append(formatted_row)

            # Combine all rows
            data_comp = [header_row1_comp, header_row2_comp, header_row3_comp] + comp_table_rows

            # Calculate column widths - adjust for better display
            available_width_comp = doc.width
            if len(comp_cols) > 0:
                # First column gets width for company names
                first_w = available_width_comp * 0.14  # Increased from 0.12
                
                # Distribute remaining width with more space for complex columns
                rem_w = available_width_comp - first_w
                
                # Define column width factors based on content complexity
                # Columns with longer headers or more complex data get more width
                width_factors = []
                for i, col in enumerate(comp_cols[1:], 1):  # Skip first column (Ticker)
                    col_name = str(col)
                    # Give more space to columns with complex headers
                    if any(term in col_name for term in ['EBITDAR', 'FCF+Rents', 'TD+COL']):
                        width_factors.append(1.3)  # 30% wider
                    elif any(term in col_name for term in ['EBITDA', 'Margin', 'Debt']):
                        width_factors.append(1.1)  # 10% wider
                    else:
                        width_factors.append(0.9)  # 10% narrower
                
                # Normalize factors to ensure total width is correct
                total_factor = sum(width_factors)
                normalized_factors = [f / total_factor for f in width_factors]
                
                # Calculate column widths based on normalized factors
                col_widths = [rem_w * factor for factor in normalized_factors]
                
                comp_col_widths = [first_w] + col_widths
            else:
                comp_col_widths = []

            # Create table style with reduced padding to fit on page
            comp_style = TableStyle([
                # Span the title across all columns in first row
                ('SPAN', (0, 0), (-1, 0)),
                # Background color for header rows
                ('BACKGROUND', (0, 0), (-1, 2), colors.HexColor('#44546A')),
                ('TEXTCOLOR', (0, 0), (-1, 2), colors.whitesmoke),
                # Span the group headers in second row
                ('SPAN', (1, 1), (7, 1)),  # LTM spans columns 1-7
                ('SPAN', (8, 1), (11, 1)),  # 3-Year Average spans columns 8-11
                # Alignments
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # Left align first column
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),  # Center align other columns
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),  # Center align first row (title)
                # Font styling
                ('FONTNAME', (0, 0), (-1, 2), 'Helvetica-Bold'),
                # Increased padding for header rows
                ('BOTTOMPADDING', (0, 0), (-1, 1), 1),
                ('TOPPADDING', (0, 0), (-1, 1), 1),
                # Extra padding for the complex column header row
                ('BOTTOMPADDING', (0, 2), (-1, 2), 3),
                ('TOPPADDING', (0, 2), (-1, 2), 3),
                # Increased padding for data rows
                ('BOTTOMPADDING', (0, 3), (-1, -1), 1),
                ('TOPPADDING', (0, 3), (-1, -1), 1),
                # White background for data rows
                ('BACKGROUND', (0, 3), (-1, -1), colors.white),
                # Table borders
                ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black),  # Line below title
                ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.black),  # Line below group headers
                ('LINEBELOW', (0, 2), (-1, 2), 0.5, colors.black),  # Line below column headers
                # Increased cell padding
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                # Add light gray background only to first company row
                ('BACKGROUND', (0, 3), (-1, 3), colors.lightgrey),
                # Add grid lines for better readability
                ('GRID', (0, 3), (-1, -1), 0.25, colors.lightgrey),
            ])

            # Emphasize AVERAGE and MEDIAN rows
            base_row_idx = 3  # Data rows start at index 3 (after 3 header rows)
            for i, row in enumerate(comp_table_rows):
                abs_r = base_row_idx + i
                try:
                    first_val = row[0].text
                    if "<i>" in first_val:  # Remove italic tags for comparison
                        first_val = first_val.replace("<i>", "").replace("</i>", "")
                except Exception:
                    first_val = ''
                    
                if first_val.upper() in ("AVERAGE", "MEDIAN"):
                    # Add line above these rows
                    comp_style.add('LINEABOVE', (0, abs_r), (-1, abs_r), 0.5, colors.black)
                    # Make text bold and add background color
                    comp_style.add('BACKGROUND', (0, abs_r), (-1, abs_r), colors.lightgrey)
                    # Make text bold
                    for j in range(len(row)):
                        try:
                            cell_text = row[j].text
                            row[j] = Paragraph(f"<b>{cell_text}</b>", 
                                              comp_data_first_col_style if j == 0 else comp_data_style)
                        except Exception:
                            pass

            comp_table = Table(data_comp, colWidths=comp_col_widths)
            comp_table.setStyle(comp_style)
            elements.append(Spacer(1, 12))
            elements.append(KeepTogether(comp_table))
        except Exception:
            pass

    doc.build(elements, onFirstPage=draw_aqrr_header, onLaterPages=draw_aqrr_header)
    buffer.seek(0)
    return buffer.getvalue()


if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Generate a financial PDF for a ticker using HFA and FSA JSON files and save it locally.')
    parser.add_argument('-t', '--ticker', help='Ticker symbol used to locate JSON files (e.g., ELME)')
    parser.add_argument('-o', '--output', help='Output PDF filename (default: <ticker>_report.pdf)')
    args = parser.parse_args()

    ticker = args.ticker.strip() if args.ticker else input('Enter ticker symbol: ').strip()
    if not ticker:
        print('Error: Ticker is required.')
        sys.exit(1)

    try:
        pdf_bytes = build_pdf_bytes_from_ticker(ticker)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f'Error: {e}')
        sys.exit(1)

    # Determine output path and filename
    year = datetime.now().year
    default_dir = os.path.join('output', 'pdf', 'AQRR')
    os.makedirs(default_dir, exist_ok=True)
    default_filename = f"{ticker}_AQRR_{year}.pdf"
    out_path = args.output if args.output else os.path.join(default_dir, default_filename)

    try:
        with open(out_path, 'wb') as f:
            f.write(pdf_bytes)
        print(f'Saved PDF to {os.path.abspath(out_path)}')
    except Exception as e:
        print(f'Failed to write output file: {e}')
        sys.exit(1)