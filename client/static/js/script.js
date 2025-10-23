async function checkAuthentication() {
    const authToken = localStorage.getItem('authToken');
    const isAuthenticated = sessionStorage.getItem('isAuthenticated');

    try {
        // First, try to verify with server (this checks both cookie and token)
        const response = await fetch('/api/v1/auth/verify', {
            method: 'GET',
            headers: {
                'Authorization': authToken ? `Bearer ${authToken}` : '',
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.authenticated) {
            // Server says we're authenticated, sync local storage
            if (!authToken) {
                localStorage.setItem('authToken', data.token);
            }
            if (!isAuthenticated) {
                sessionStorage.setItem('isAuthenticated', 'true');
            }

            setupAuthenticatedFetch(data.token);
            return true;
        } else {
            localStorage.removeItem('authToken');
            sessionStorage.removeItem('isAuthenticated');

            if (window.location.pathname !== '/') {
                window.location.href = '/';
            }
            return false;
        }
    } catch (error) {
        console.error('Auth verification failed:', error);

        if (!isAuthenticated || !authToken) {
            if (window.location.pathname !== '/') {
                window.location.href = '/';
            }
            return false;
        }
        setupAuthenticatedFetch(authToken);
        return true;
    }
}

function setupAuthenticatedFetch(authToken) {
    const originalFetch = window.fetch;
    window.fetch = function (...args) {
        if (args[1]) {
            args[1].headers = {
                ...args[1].headers,
                'Authorization': `Bearer ${authToken}`
            };
        } else {
            args[1] = {
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            };
        }
        return originalFetch.apply(this, args);
    };
}

function logout() {
    fetch('/api/v1/auth/logout', { method: 'POST' })
        .then(() => {
            localStorage.removeItem('authToken');
            sessionStorage.removeItem('isAuthenticated');
            window.location.href = '/';
        })
        .catch(() => {
            localStorage.removeItem('authToken');
            sessionStorage.removeItem('isAuthenticated');
            window.location.href = '/';
        });
}

class AQRRTool {
    constructor() {
        this.currentCompany = null;
        this.currentPdfUrl = null;
        this.currentWordUrl = null;
        this.conversationHistory = [];
        this.companies = [];
        // Lineage chat state
        this.lineageSessionId = null;
        this.lineageChatOpen = false;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.loadCompanies();
        this.initTabs();
        this.syncCompanySelectors();
        this.initLineageChatWidget();
    }

    setupEventListeners() {
        // Initialize comboboxes
        this.initCombobox('company-select');
        this.initCombobox('company-select-reports');

        // AQRR Analysis tab events
        document.getElementById('generate-btn').addEventListener('click', () => {
            this.generateAQRR();
        });

        document.getElementById('download-pdf-btn').addEventListener('click', () => {
            this.downloadPDF();
        });

        document.getElementById('download-docx-btn').addEventListener('click', () => {
            this.downloadDOCX();
        });

        // Reports & Analytics tab events
        document.getElementById('submit-question-btn').addEventListener('click', () => {
            this.submitQuestion();
        });

        document.getElementById('clear-question-btn').addEventListener('click', () => {
            this.clearQuestion();
        });

        // Example questions
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('example-question')) {
                const questionText = e.target.textContent.trim();
                document.getElementById('question-input').value = questionText;
            }
        });


        // Enter key submission
        document.getElementById('question-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.ctrlKey) {
                this.submitQuestion();
            }
        });
    }

    initTabs() {
        const tabButtons = document.querySelectorAll('.tab-button');
        const tabContents = document.querySelectorAll('.tab-content');

        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const targetTab = button.id.replace('tab-', 'content-');

                // Update active tab button
                tabButtons.forEach(btn => btn.classList.remove('active'));
                button.classList.add('active');

                // Show target content
                tabContents.forEach(content => content.classList.add('hidden'));
                document.getElementById(targetTab).classList.remove('hidden');

                // Control lineage chat widget visibility based on tab
                this.updateLineageChatVisibility();

                this.syncCompanySelectors();
            });
        });
    }

    syncCompanySelectors() {
        const mainInput = document.getElementById('company-select');
        const reportsInput = document.getElementById('company-select-reports');
        const mainValue = mainInput.dataset.value || '';
        const reportsValue = reportsInput.dataset.value || '';
        
        if (mainValue !== reportsValue) {
            if (mainValue) {
                this.setComboboxValue('company-select-reports', mainValue);
            } else {
                this.setComboboxValue('company-select-reports', '');
            }
        }
    }

    initCombobox(inputId) {
        const container = document.getElementById(inputId).closest('.custom-combobox');
        const input = container.querySelector('.combobox-input');
        const toggle = container.querySelector('.combobox-toggle');
        const clear = container.querySelector('.combobox-clear');
        const dropdown = container.querySelector('.combobox-dropdown');
        const search = container.querySelector('.combobox-search');

        // Toggle dropdown
        toggle.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.toggleCombobox(inputId);
        });

        // Clear selection
        clear.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.clearCombobox(inputId);
        });

        // Open dropdown on input click
        input.addEventListener('click', (e) => {
            e.preventDefault();
            this.openCombobox(inputId);
        });

        // Search functionality
        search.addEventListener('input', (e) => {
            this.filterComboboxOptions(inputId, e.target.value);
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!container.contains(e.target)) {
                this.closeCombobox(inputId);
            }
        });

        // Handle keyboard navigation
        search.addEventListener('keydown', (e) => {
            this.handleComboboxKeyboard(e, inputId);
        });
    }

    toggleCombobox(inputId) {
        const container = document.getElementById(inputId).closest('.custom-combobox');
        const dropdown = container.querySelector('.combobox-dropdown');
        const isOpen = !dropdown.classList.contains('hidden');
        
        if (isOpen) {
            this.closeCombobox(inputId);
        } else {
            this.openCombobox(inputId);
        }
    }

    openCombobox(inputId) {
        // Close other comboboxes first
        document.querySelectorAll('.combobox-dropdown').forEach(dd => {
            if (dd !== document.getElementById(inputId).querySelector('.combobox-dropdown')) {
                dd.classList.add('hidden');
            }
        });

        const container = document.getElementById(inputId).closest('.custom-combobox');
        const dropdown = container.querySelector('.combobox-dropdown');
        const search = container.querySelector('.combobox-search');
        const toggle = container.querySelector('.combobox-toggle svg');

        dropdown.classList.remove('hidden');
        toggle.style.transform = 'rotate(180deg)';
        
        // Focus search input
        setTimeout(() => {
            search.focus();
            search.value = '';
            this.filterComboboxOptions(inputId, '');
        }, 10);
    }

    closeCombobox(inputId) {
        const container = document.getElementById(inputId).closest('.custom-combobox');
        const dropdown = container.querySelector('.combobox-dropdown');
        const toggle = container.querySelector('.combobox-toggle svg');

        dropdown.classList.add('hidden');
        toggle.style.transform = 'rotate(0deg)';
    }

    clearCombobox(inputId) {
        this.setComboboxValue(inputId, '');
        this.handleCompanySelection('');
    }

    setComboboxValue(inputId, value) {
        const input = document.getElementById(inputId);
        const clear = input.closest('.custom-combobox').querySelector('.combobox-clear');
        
        if (value) {
            const company = this.companies?.find(c => c.ticker === value);
            input.value = company ? company.title : value;
            input.dataset.value = value;
            clear.classList.remove('hidden');
        } else {
            input.value = '';
            input.dataset.value = '';
            clear.classList.add('hidden');
        }
    }

    populateComboboxOptions(inputId) {
        const container = document.getElementById(inputId).closest('.custom-combobox');
        const optionsContainer = container.querySelector('.combobox-options');
        
        if (!this.companies || this.companies.length === 0) {
            optionsContainer.innerHTML = '<div class="combobox-option px-3 py-2 text-sm text-gray-500 cursor-default">No companies available</div>';
            return;
        }

        optionsContainer.innerHTML = '';
        this.companies.forEach(company => {
            const option = document.createElement('div');
            option.className = 'combobox-option px-3 py-2 text-sm cursor-pointer hover:bg-pru-blue hover:text-white transition-colors duration-150';
            option.textContent = company.title;
            option.dataset.value = company.ticker;
            option.dataset.title = company.title.toLowerCase();
            
            option.addEventListener('click', () => {
                this.setComboboxValue(inputId, company.ticker);
                this.closeCombobox(inputId);
                this.handleCompanySelection(company.ticker);
            });
            
            optionsContainer.appendChild(option);
        });
    }

    filterComboboxOptions(inputId, searchTerm) {
        const container = document.getElementById(inputId).closest('.custom-combobox');
        const options = container.querySelectorAll('.combobox-option');
        const term = searchTerm.toLowerCase();

        let visibleCount = 0;
        options.forEach(option => {
            const title = option.dataset.title;
            const ticker = option.dataset.value?.toLowerCase();
            
            if (!title) {
                option.style.display = 'block';
                return;
            }

            const matchesTitle = title.includes(term);
            const matchesTicker = ticker?.includes(term);
            
            if (matchesTitle || matchesTicker) {
                option.style.display = 'block';
                visibleCount++;
            } else {
                option.style.display = 'none';
            }
        });

        // Show "no results" message if no matches
        if (visibleCount === 0 && searchTerm.trim()) {
            const noResults = container.querySelector('.no-results');
            if (!noResults) {
                const noResultsDiv = document.createElement('div');
                noResultsDiv.className = 'no-results px-3 py-2 text-sm text-gray-500 cursor-default';
                noResultsDiv.textContent = 'No companies found';
                container.querySelector('.combobox-options').appendChild(noResultsDiv);
            }
        } else {
            const noResults = container.querySelector('.no-results');
            if (noResults) {
                noResults.remove();
            }
        }
    }

    handleComboboxKeyboard(e, inputId) {
        const container = document.getElementById(inputId).closest('.custom-combobox');
        const visibleOptions = Array.from(container.querySelectorAll('.combobox-option')).filter(opt => opt.style.display !== 'none');
        const currentHighlighted = container.querySelector('.combobox-option.highlighted');
        
        let currentIndex = currentHighlighted ? visibleOptions.indexOf(currentHighlighted) : -1;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                currentIndex = Math.min(currentIndex + 1, visibleOptions.length - 1);
                this.highlightComboboxOption(container, visibleOptions, currentIndex);
                break;
            case 'ArrowUp':
                e.preventDefault();
                currentIndex = Math.max(currentIndex - 1, 0);
                this.highlightComboboxOption(container, visibleOptions, currentIndex);
                break;
            case 'Enter':
                e.preventDefault();
                if (currentHighlighted && currentHighlighted.dataset.value) {
                    this.setComboboxValue(inputId, currentHighlighted.dataset.value);
                    this.closeCombobox(inputId);
                    this.handleCompanySelection(currentHighlighted.dataset.value);
                }
                break;
            case 'Escape':
                e.preventDefault();
                this.closeCombobox(inputId);
                break;
        }
    }

    highlightComboboxOption(container, visibleOptions, index) {
        // Remove previous highlight
        container.querySelectorAll('.combobox-option').forEach(opt => {
            opt.classList.remove('highlighted', 'bg-pru-blue', 'text-white');
        });

        // Add highlight to current option
        if (index >= 0 && index < visibleOptions.length) {
            const option = visibleOptions[index];
            option.classList.add('highlighted', 'bg-pru-blue', 'text-white');
            option.scrollIntoView({ block: 'nearest' });
        }
    }

    async loadCompanies() {
        try {
            const response = await fetch('/api/v1/companies');
            const data = await response.json();
            this.companies = data.companies || [];
            this.populateComboboxOptions('company-select');
            this.populateComboboxOptions('company-select-reports');
        } catch (error) {
            console.error('Error loading companies:', error);
            this.showNotification('Error loading companies', 'error');
        }
    }

    showAnalyzingIndicator(question) {
        const conversationHistory = document.getElementById('conversation-history');
        const analysisResults = document.getElementById('analysis-results');
        const emptyState = document.getElementById('reports-empty-state');

        // Show results area if hidden
        emptyState.classList.add('hidden');
        analysisResults.classList.remove('hidden');

        // Create analyzing indicator
        const analyzingDiv = document.createElement('div');
        analyzingDiv.id = 'analyzing-indicator';
        analyzingDiv.className = 'analyzing-indicator';
        analyzingDiv.innerHTML = `
            <span class="analyzing-text">Analyzing your question</span>
            <div class="analyzing-dots">
                <div class="analyzing-dot"></div>
                <div class="analyzing-dot"></div>
                <div class="analyzing-dot"></div>
            </div>
        `;

        conversationHistory.appendChild(analyzingDiv);
        conversationHistory.scrollTop = conversationHistory.scrollHeight;
    }

    hideAnalyzingIndicator() {
        const indicator = document.getElementById('analyzing-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    handleCompanySelection(companyId) {
        if (this.currentCompany === companyId && companyId) {
            this.setComboboxValue('company-select', companyId);
            this.setComboboxValue('company-select-reports', companyId);
            return;
        }

        this.currentCompany = companyId;
        this.cleanup();
        this.currentPdfUrl = null;
        this.currentWordUrl = null;
        this.setComboboxValue('company-select', companyId);
        this.setComboboxValue('company-select-reports', companyId);

        // Update AQRR tab elements
        const generateBtn = document.getElementById('generate-btn');
        if (companyId) {
            generateBtn.disabled = false;
            generateBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        } else {
            generateBtn.disabled = true;
            generateBtn.classList.add('opacity-50', 'cursor-not-allowed');
        }

        // Update Reports tab elements
        const questionInput = document.getElementById('question-input');
        const submitBtn = document.getElementById('submit-question-btn');

        if (companyId) {
            questionInput.disabled = false;
            questionInput.placeholder = 'Ask a question about the selected company...';
            submitBtn.disabled = false;
            submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        } else {
            questionInput.disabled = true;
            questionInput.placeholder = 'Select a company first...';
            questionInput.value = '';
            submitBtn.disabled = true;
            submitBtn.classList.add('opacity-50', 'cursor-not-allowed');
        }

        // Reset states
        this.hideAllStates();
        this.showEmptyState();
        this.clearConversation();

        // Reset lineage chat session and UI
        this.resetLineageSession();
        this.updateLineageUiOnTicker();
        this.updateLineageChatVisibility();
    }

    async submitQuestion() {
        if (!this.currentCompany) return;
        const questionInput = document.getElementById('question-input');
        const question = questionInput.value.trim();

        if (!question) {
            this.showNotification('Please enter a question', 'error');
            return;
        }
        try {
            this.showQueryLoading();
            this.showAnalyzingIndicator(question); 

            const payload = {
                company_id: this.currentCompany,
                question: question
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
                this.hideAnalyzingIndicator(); 
                this.addToConversation(question, data.response);
                questionInput.value = '';
            } else {
                throw new Error('Failed to process query');
            }
        } catch (error) {
            console.error('Error processing query:', error);
            this.hideAnalyzingIndicator(); 
            this.showNotification('Error processing query', 'error');
        } finally {
            this.hideQueryLoading();
        }
    }

    addToConversation(question, response) {
        const conversationHistory = document.getElementById('conversation-history');
        const analysisResults = document.getElementById('analysis-results');
        const emptyState = document.getElementById('reports-empty-state');

        // Show results area
        emptyState.classList.add('hidden');
        analysisResults.classList.remove('hidden');

        // Create conversation item
        const conversationItem = document.createElement('div');
        conversationItem.className = 'conversation-item border rounded-lg p-4 bg-gradient-to-br from-gray-50 to-blue-50';

        conversationItem.innerHTML = `
            <div class="mb-3">
                <div class="flex items-center mb-2">
                    <div class="w-6 h-6 bg-pru-blue rounded-full flex items-center justify-center mr-3">
                        <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                        </svg>
                    </div>
                    <span class="font-medium text-gray-900 text-sm">Question</span>
                </div>
                <p class="text-gray-700 text-sm ml-9">${question}</p>
            </div>
            <div class="border-t pt-3">
                <div class="flex items-center mb-2">
                    <div class="w-6 h-6 bg-pru-purple rounded-full flex items-center justify-center mr-3">
                        <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                        </svg>
                    </div>
                    <span class="font-medium text-gray-900 text-sm">AI Analysis</span>
                </div>
                <div class="ml-9 prose prose-sm max-w-none">
                    <div class="text-gray-700 text-sm whitespace-pre-wrap">${this.formatResponse(response)}</div>
                </div>
            </div>
        `;

        conversationHistory.appendChild(conversationItem);

        // Scroll to bottom
        conversationHistory.scrollTop = conversationHistory.scrollHeight;

        // Store in conversation history
        this.conversationHistory.push({ question, response, timestamp: new Date() });

        // Keep only last 10 conversations
        if (this.conversationHistory.length > 10) {
            this.conversationHistory = this.conversationHistory.slice(-10);
            if (conversationHistory.children.length > 10) {
                conversationHistory.removeChild(conversationHistory.firstChild);
            }
        }
    }

    formatResponse(response) {
        return response
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/^• /gm, '• ')
            .replace(/\n\n/g, '\n\n');
    }

    clearQuestion() {
        document.getElementById('question-input').value = '';
    }

    clearConversation() {
        document.getElementById('conversation-history').innerHTML = '';
        document.getElementById('reports-empty-state').classList.remove('hidden');
        document.getElementById('analysis-results').classList.add('hidden');
        this.conversationHistory = [];
    }

    showQueryLoading() {
        document.getElementById('query-loading-state').classList.remove('hidden');
        document.getElementById('submit-question-btn').disabled = true;
    }

    hideQueryLoading() {
        document.getElementById('query-loading-state').classList.add('hidden');
        if (this.currentCompany) {
            document.getElementById('submit-question-btn').disabled = false;
        }
    }

    resetLineageSession() {
        this.lineageSessionId = null;
        const messages = document.getElementById('lineage-chat-messages');
        if (messages) {
            messages.innerHTML = '';
        }
    }

    async startLineageSession() {
        if (!this.currentCompany) return;

        try {
            const res = await fetch('/api/v1/lineage/chat/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ticker: this.currentCompany })
            });

            if (!res.ok) throw new Error('Failed to start lineage chat');

            const data = await res.json();
            this.lineageSessionId = data.session_id;

            this.updateLineageUiOnTicker();

            const messages = document.getElementById('lineage-chat-messages');
            if (messages) {
                messages.innerHTML = '';
                this.addLineageMessage(
                    'assistant',
                    `✅ Lineage chat ready for ${this.currentCompany}! Ask about any metric and period from the generated AQRR (e.g., "Revenue 2024", "Operating Expenses Q1 2025").`
                );
            }

            // Show notification that chat is ready
            this.showNotification('Lineage chat is now ready!', 'success');

        } catch (err) {
            console.error('Lineage session error:', err);
            this.showNotification('Unable to start lineage chat. Check server logs.', 'error');
        }
    }

    async generateAQRR() {
        if (!this.currentCompany) return;
        try {
            this.showLoadingState();
            const response = await fetch('/api/v1/aqrr-pdf-word', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ ticker: this.currentCompany })
            });

            if (response.ok) {
                const data = await response.json();
                if (data && data.pdf && data.word) {
                    // Store both PDF and Word URLs
                    this.currentPdfUrl = data.pdf.url || new URL(data.pdf.path, window.location.origin).href;
                    this.currentWordUrl = data.word.url || new URL(data.word.path, window.location.origin).href;
                    // Start lineage session AFTER successful AQRR generation
                    await this.startLineageSession();
                    this.showSuccessState();
                    this.showPdfPreview();
                    this.updateLineageChatVisibility();

                } else {
                    throw new Error('Invalid response from server');
                }
            } else {
                let msg = 'Failed to generate AQRR';
                try {
                    const err = await response.json();
                    if (err && err.detail) msg = err.detail;
                } catch (_) { }
                throw new Error(msg);
            }
        } catch (error) {
            console.error('Error generating AQRR:', error);
            const friendly = (error && error.message) ? error.message : 'Unknown error generating AQRR';
            this.showNotification(`Error generating AQRR: ${friendly}`, 'error');
            this.hideAllStates();
        }
    }

    showLoadingState() {
        this.hideAllStates();
        document.getElementById('loading-state').classList.remove('hidden');
        document.getElementById('generate-btn').disabled = true;
    }

    showSuccessState() {
        document.getElementById('loading-state').classList.add('hidden');
        document.getElementById('success-state').classList.remove('hidden');
        document.getElementById('download-pdf-btn').classList.remove('hidden');
        document.getElementById('download-docx-btn').classList.remove('hidden');
        document.getElementById('generate-btn').disabled = false;
    }

    hideAllStates() {
        document.getElementById('loading-state').classList.add('hidden');
        document.getElementById('success-state').classList.add('hidden');
        document.getElementById('download-pdf-btn').classList.add('hidden');
        document.getElementById('download-docx-btn').classList.add('hidden');
    }

    showEmptyState() {
        document.getElementById('empty-state').classList.remove('hidden');
        document.getElementById('pdf-preview').classList.add('hidden');
    }

    async showPdfPreview() {
        if (this.currentPdfUrl) {
            document.getElementById('empty-state').classList.add('hidden');
            document.getElementById('pdf-preview').classList.remove('hidden');

            try {
                // Fetch PDF and convert to blob
                const response = await fetch(this.currentPdfUrl);
                if (!response.ok) throw new Error('Failed to fetch PDF');

                const blob = await response.blob();
                const blobUrl = URL.createObjectURL(blob);

                // Clean up previous blob URL if exists
                const iframe = document.getElementById('pdf-frame');
                if (iframe.src && iframe.src.startsWith('blob:')) {
                    URL.revokeObjectURL(iframe.src);
                }

                iframe.src = blobUrl;
            } catch (error) {
                console.error('Error loading PDF preview:', error);
                this.showNotification('Error loading PDF preview', 'error');
                document.getElementById('pdf-frame').src = this.currentPdfUrl;
            }
        }
    }

    cleanup() {
        const iframe = document.getElementById('pdf-frame');
        if (iframe && iframe.src && iframe.src.startsWith('blob:')) {
            URL.revokeObjectURL(iframe.src);
        }
    }

    getQuarterFileName(ticker, extension) {
        const today = new Date();
        const year = today.getFullYear();
        const month = (today.getMonth() + 1).toString().padStart(2, '0');
        const day = today.getDate().toString().padStart(2, '0');
        const hours = today.getHours().toString().padStart(2, '0');
        const minutes = today.getMinutes().toString().padStart(2, '0');
        const seconds = today.getSeconds().toString().padStart(2, '0');

        // Determine quarter based on March-end fiscal quarters
        let quarter;
        if (month >= 4 && month <= 6) {
            quarter = 'Q1'; // Apr - Jun
        } else if (month >= 7 && month <= 9) {
            quarter = 'Q2'; // Jul - Sep
        } else if (month >= 10 && month <= 12) {
            quarter = 'Q3'; // Oct - Dec
        } else {
            quarter = 'Q4'; // Jan - Mar
        }

        const timestamp = `${year}-${month}-${day}_${hours}${minutes}${seconds}`;

        return `${ticker}_AQRR_${quarter}_${timestamp}.${extension}`;
    }

    downloadPDF() {
        if (this.currentPdfUrl && this.currentCompany) {
            const link = document.createElement('a');
            link.href = this.currentPdfUrl;
            link.download = this.getQuarterFileName(this.currentCompany, 'pdf');
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showNotification('PDF downloaded successfully!', 'success');
        }
    }

    downloadDOCX() {
        if (this.currentWordUrl && this.currentCompany) {
            const link = document.createElement('a');
            link.href = this.currentWordUrl;
            link.download = this.getQuarterFileName(this.currentCompany, 'docx');
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showNotification('DOCX downloaded successfully!', 'success');
        }
    }

    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `fixed top-4 right-4 p-4 rounded-lg shadow-lg z-50 transition-all duration-300 transform translate-x-full`;

        const bgColor = type === 'error' ? 'bg-red-500' : type === 'success' ? 'bg-green-500' : 'bg-blue-500';
        notification.classList.add(bgColor, 'text-white');

        notification.innerHTML = `
            <div class="flex items-center">
                <span>${message}</span>
                <button class="ml-4 text-white hover:text-gray-200" onclick="this.parentElement.parentElement.remove()">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
        `;

        document.body.appendChild(notification);

        // Animate in
        setTimeout(() => {
            notification.classList.remove('translate-x-full');
        }, 100);

        // Auto remove after 5 seconds
        setTimeout(() => {
            notification.classList.add('translate-x-full');
            setTimeout(() => {
                if (notification.parentElement) {
                    notification.remove();
                }
            }, 300);
        }, 5000);
    }

    updateLineageChatVisibility() {
        const widget = document.getElementById('lineage-chat-widget');
        const currentTab = document.querySelector('.tab-button.active');

        if (!widget || !currentTab) return;

        // Show widget only on AQRR Analysis tab AND after PDF is generated
        const isAnalysisTab = currentTab.id === 'tab-analysis';
        const hasPdf = !!(this.currentPdfUrl && this.lineageSessionId);

        if (isAnalysisTab && hasPdf) {
            widget.classList.remove('hidden');
        } else {
            widget.classList.add('hidden');
            const panel = document.getElementById('lineage-chat-panel');
            if (panel) {
                panel.classList.add('hidden');
                this.lineageChatOpen = false;
            }
        }
    }

    // ---------------- Lineage Chat Widget ----------------
    initLineageChatWidget() {
        const toggleBtn = document.getElementById('lineage-chat-toggle');
        const panel = document.getElementById('lineage-chat-panel');
        const closeBtn = document.getElementById('lineage-chat-close');
        const sendBtn = document.getElementById('lineage-chat-send');
        const input = document.getElementById('lineage-chat-input');

        if (!toggleBtn || !panel || !closeBtn || !sendBtn || !input) return;

        toggleBtn.addEventListener('click', () => {
            this.lineageChatOpen = !this.lineageChatOpen;
            panel.classList.toggle('hidden', !this.lineageChatOpen);
            if (this.lineageChatOpen) {
                this.updateLineageUiOnTicker();
                // Don't auto-start session on toggle - only after AQRR generation
            }
        });

        closeBtn.addEventListener('click', () => {
            this.lineageChatOpen = false;
            panel.classList.add('hidden');
        });

        sendBtn.addEventListener('click', () => {
            this.handleLineageSend();
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleLineageSend();
            }
        });

        // Initialize UI state
        this.updateLineageUiOnTicker();
        this.updateLineageChatVisibility();
    }

    updateLineageUiOnTicker() {
        const tickerEl = document.getElementById('lineage-chat-ticker');
        const input = document.getElementById('lineage-chat-input');
        const sendBtn = document.getElementById('lineage-chat-send');
        if (tickerEl) tickerEl.textContent = this.currentCompany || 'None';
        // Enable chat only if we have both company and session
        const enabled = !!(this.currentCompany && this.lineageSessionId);

        if (input) input.disabled = !enabled;
        if (sendBtn) sendBtn.disabled = !enabled;

        if (!this.currentCompany) {
            const messages = document.getElementById('lineage-chat-messages');
            if (messages) {
                messages.innerHTML = '<div class="text-xs text-gray-500">Select a company to start.</div>';
            }
        } else if (!this.lineageSessionId) {
            const messages = document.getElementById('lineage-chat-messages');
            if (messages) {
                messages.innerHTML = '<div class="text-xs text-gray-500">Generate AQRR first to start lineage chat.</div>';
            }
        }
    }

    async ensureLineageSession() {
        try {
            // If we already have a session, keep it unless ticker changed (we don't store ticker here; simplest: restart always)
            this.lineageSessionId = null;
            const res = await fetch('/api/v1/lineage/chat/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ticker: this.currentCompany })
            });
            if (!res.ok) throw new Error('Failed to start lineage chat');
            const data = await res.json();
            this.lineageSessionId = data.session_id;

            // Reset messages with a welcome line
            const messages = document.getElementById('lineage-chat-messages');
            if (messages) {
                messages.innerHTML = '';
                this.addLineageMessage('assistant', `Loaded latest HFA JSON for ${this.currentCompany}. Ask about any metric and period (e.g., "Revenue 2024", "Operating Expenses Q1 2025").`);
            }
        } catch (err) {
            console.error('Lineage session error:', err);
            this.showNotification('Unable to start lineage chat. Check server logs.', 'error');
        }
    }

    addLineageAnalyzingIndicator() {
        const container = document.getElementById('lineage-chat-messages');
        if (!container) return;

        const wrapper = document.createElement('div');
        wrapper.id = 'lineage-analyzing-indicator';
        wrapper.className = 'flex justify-start mb-2';

        const bubble = document.createElement('div');
        bubble.className = 'max-w-[85%] px-3 py-2 rounded-lg bg-blue-50 border border-blue-200';
        bubble.innerHTML = `
            <div class="flex items-center gap-2 text-sm text-blue-700">
                <span>Analyzing...</span>
                <div class="analyzing-dots">
                    <div class="analyzing-dot"></div>
                    <div class="analyzing-dot"></div>
                    <div class="analyzing-dot"></div>
                </div>
            </div>
        `;

        wrapper.appendChild(bubble);
        container.appendChild(wrapper);
        container.scrollTop = container.scrollHeight;
    }

    hideLineageAnalyzingIndicator() {
        const indicator = document.getElementById('lineage-analyzing-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    addLineageMessage(role, text) {
        const container = document.getElementById('lineage-chat-messages');
        if (!container) return;
        const wrapper = document.createElement('div');
        const isUser = role === 'user';
        wrapper.className = `flex ${isUser ? 'justify-end' : 'justify-start'}`;
        const bubble = document.createElement('div');
        bubble.className = `max-w-[85%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap ${isUser ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-800'}`;
        bubble.textContent = text || '';
        wrapper.appendChild(bubble);
        container.appendChild(wrapper);
        container.scrollTop = container.scrollHeight;
    }

    async handleLineageSend() {
        if (!this.currentCompany || !this.lineageSessionId) {
            this.showNotification('Generate AQRR first to start lineage chat', 'error');
            return;
        }
        const input = document.getElementById('lineage-chat-input');
        const sendBtn = document.getElementById('lineage-chat-send');
        const text = (input.value || '').trim();
        if (!text) return;

        // Append user message and clear input
        this.addLineageMessage('user', text);
        this.addLineageAnalyzingIndicator(); // Add this line
        input.value = '';
        sendBtn.disabled = true;

        try {
            const res = await fetch('/api/v1/lineage/chat/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.lineageSessionId, message: text })
            });
            if (!res.ok) throw new Error('Failed to send message');
            const data = await res.json();
            this.hideLineageAnalyzingIndicator(); // Add this line
            this.addLineageMessage('assistant', data.reply || '(no reply)');
        } catch (err) {
            console.error('Lineage chat error:', err);
            this.hideLineageAnalyzingIndicator(); // Add this line
            this.addLineageMessage('assistant', 'Sorry, there was an error processing your request.');
        } finally {
            if (this.currentCompany && this.lineageSessionId) {
                sendBtn.disabled = false;
            }
        }
    }
}


document.addEventListener('DOMContentLoaded', async () => {
    const isAuthenticated = await checkAuthentication();
    if (isAuthenticated) {
        new AQRRTool();
    }
});