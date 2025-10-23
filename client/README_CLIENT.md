# PGIM Dealio Frontend

A modern web interface for SEC EDGAR financial data analysis and AQRR report generation. Built with vanilla JavaScript and Tailwind CSS.

## Project Structure

```
client/
├── templates/
│   └── index.html                  # Main application template
├── static/
│   ├── js/
│   │   └── script.js              # Main application logic
│   ├── css/
│   │   └── styles.css             # Custom styles
│   └── images/
│       └── logo.png               # PGIM brand assets
```

## Features

### **Dual-Tab Interface**
- **AQRR Analysis Tab**: Generate and download comprehensive financial reports
- **Reports & Analytics Tab**: AI-powered Q&A and report generation

### **Key Capabilities**
- Company selection from predefined list
- One-click AQRR PDF generation with live preview
- AI assistant with Q&A and Report modes
- Interactive conversation history
- Real-time status updates and notifications

## Technical Overview

### **Core Class: AQRRTool**
```javascript
class AQRRTool {
    constructor() {
        this.currentCompany = null;
        this.currentPdfUrl = null;
        this.conversationHistory = [];
    }
}
```

### **API Integration**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies` | GET | Fetch available companies |
| `/api/v1/pdf/{company_id}` | GET | Generate AQRR PDF |
| `/api/v1/query` | POST | Submit AI analysis queries |

#### **1. Get Companies List**
```javascript
// GET /api/v1/companies
// Request: No body required

// Response:
{
  "companies": [
    {"ticker": "AME", "title": "AMETEK INC"},
    {"ticker": "ELME", "title": "ELME COMMUNITIES"},
    {"ticker": "KRG", "title": "KITE REALTY GROUP TRUST"},
    {"ticker": "SAFE", "title": "SAFEHOLD INC."},
    {"ticker": "STAG", "title": "STAG INDUSTRIAL, INC."},
    {"ticker": "STE", "title": "STERIS PLC"},
    {"ticker": "TMO", "title": "THERMO FISHER SCIENTIFIC INC."},
    {"ticker": "WAT", "title": "WATERS CORPORATION"}
  ]
}
```

#### **2. Generate AQRR PDF**
```javascript
// GET /api/v1/pdf/ELME
// Request: No body required (company ID in URL path)

// Response: Binary PDF blob
// Content-Type: application/pdf
// The response is converted to a blob URL for preview and download
```

#### **3. Submit AI Query**
```javascript
// POST /api/v1/query
// Request Body Examples:

// Q&A Mode Example:
{
  "company_id": "ELME",
  "question": "What was the company's revenue growth in Q4 2024?",
  "mode": "Q&A"
}

// Report Mode Example:
{
  "company_id": "TMO",
  "question": "Q4 2024",
  "mode": "Report"
}

// Comprehensive Analysis (Report Mode with empty question):
{
  "company_id": "SAFE",
  "question": "",
  "mode": "Report"
}

// Response:
{
  "status": "success",
  "company_id": "ELME",
  "question": "What was the company's revenue growth in Q4 2024?",
  "mode": "Q&A",
  "response": "Based on the financial statements, ELME Communities showed strong revenue growth in Q4 2024. Total revenue increased by 12.5% compared to Q4 2023, primarily driven by increased occupancy rates and rental income from new acquisitions. The company reported total revenue of $145.2 million for Q4 2024, up from $129.1 million in the prior year quarter."
}
```

### **Key Components**
- **Company Management**: Syncs selection across tabs
- **AQRR Generation**: Handles PDF creation and preview
- **AI Assistant**: Processes queries with conversation history
- **State Management**: Loading, success, and error states

## User Interface

### **Tab Navigation**
Seamless switching between AQRR and Reports tabs with synchronized company selection.

### **AQRR Analysis Panel**
- Company dropdown selection
- Generate button with loading states
- PDF preview with embedded viewer
- Download functionality

### **AI Assistant Interface**
- Mode selection (Q&A vs Report)
- Question input with example suggestions
- Conversation history with chronological display
- Real-time response handling

## API Call Examples in Code

### **Loading Companies**
```javascript
async loadCompanies() {
    try {
        const response = await fetch('/api/v1/companies');
        const data = await response.json();
        
        // Populate both dropdown selectors
        const selectors = ['company-select', 'company-select-reports'];
        selectors.forEach(selectorId => {
            const select = document.getElementById(selectorId);
            select.innerHTML = '<option value="">Choose a company...</option>';
            
            data.companies.forEach(company => {
                const option = document.createElement('option');
                option.value = company.ticker;
                option.textContent = company.title;
                select.appendChild(option);
            });
        });
    } catch (error) {
        this.showNotification('Error loading companies', 'error');
    }
}
```

### **Generating AQRR PDF**
```javascript
async generateAQRR() {
    try {
        this.showLoadingState();
        
        const response = await fetch(`/api/v1/pdf/${this.currentCompany}`);
        
        if (response.ok) {
            const blob = await response.blob();
            this.currentPdfUrl = URL.createObjectURL(blob);
            this.showSuccessState();
            this.showPdfPreview();
        } else {
            throw new Error('Failed to generate AQRR');
        }
    } catch (error) {
        this.showNotification('Error generating AQRR analysis', 'error');
    }
}
```

### **Submitting AI Query**
```javascript
async submitQuestion() {
    const questionInput = document.getElementById('question-input');
    const question = questionInput.value.trim();
    const mode = document.querySelector('input[name="analysis-mode"]:checked').value;
    
    try {
        this.showQueryLoading();
        
        const payload = {
            company_id: this.currentCompany,
            question: question || 'comprehensive analysis',
            mode: mode
        };
        
        const response = await fetch('/api/v1/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            const data = await response.json();
            this.addToConversation(question || `[${mode} Mode] Comprehensive Analysis`, data.response, mode);
            questionInput.value = '';
        } else {
            throw new Error('Failed to process query');
        }
    } catch (error) {
        this.showNotification('Error processing query', 'error');
    } finally {
        this.hideQueryLoading();
    }
}
```

## Design System

### **PGIM Brand Colors**
```javascript
colors: {
    'pru-navy': '#003366',
    'pru-blue': '#1e3a8a',
    'pru-orange': '#ea580c',
    'pru-gold': '#f59e0b',
    'pru-purple': '#7c3aed'
}
```

### **Layout**
- Responsive 12-column grid system
- Card-based design with gradients
- Professional typography and spacing
- Loading animations and transitions

## Getting Started

### **Development**
```bash
# Start the FastAPI backend
python app.py

# Access the application
open http://localhost:3030
```

### **File Structure**
- `index.html`: Main template with Tailwind CSS
- `script.js`: Application logic and API integration
- `styles.css`: Custom styling overrides

## Key Features

### **AQRR Generation Flow**
1. Select company → Enable generate button
2. Click generate → Show loading state
3. PDF created → Display success + preview
4. Download with company-specific filename

### **AI Analysis Flow**
1. Select company and mode (Q&A/Report)
2. Enter question or use examples
3. Submit → Loading indicator
4. Response added to conversation history

## Example Questions by Mode

### **Q&A Mode Examples**
- "What was the company's revenue growth?"
- "How much debt was retired this year?"
- "What are the main risk factors?"

### **Report Mode Examples**
- "Q4 2024" (specific quarter analysis)
- "FY 2024" (full year analysis)
- "" (empty for comprehensive analysis)

## Customization

### **Adding Companies**
Update the backend `/api/v1/companies` endpoint response.

### **Styling Changes**
Modify Tailwind config in `index.html` or add custom CSS in `styles.css`.

### **New Features**
Extend the `AQRRTool` class and add corresponding UI elements.

## Browser Support
- Modern browsers (Chrome 90+, Firefox 88+, Safari 14+, Edge 90+)
- ES6+ JavaScript features
- CSS Grid and Flexbox support