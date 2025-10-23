"""
RAG Query System Integration for FastAPI
Adapted from your rag_app.py
"""
import os
import logging
from pathlib import Path
from typing import Optional
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv
import httpx

load_dotenv()

class FinancialRAGQuery:
    def __init__(self, persist_directory: str = "chroma_db"):
        """Initialize the RAG Query System"""
        self.persist_directory = persist_directory
        http_client = httpx.Client(verify=False)
        
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            http_client=http_client,
            max_retries=3,
            request_timeout=60
        )
        
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            http_client=http_client,
            max_retries=3,
            request_timeout=60
        )
        
        self.vectorstore = None
        self.qa_chain = None
        self.report_chain = None
        self.setup_prompt_templates()
        self.load_vector_store()
    
    def setup_prompt_templates(self):
        """Create prompt templates for Q&A and Report Generation"""
        
        # Q&A Prompt
        self.qa_prompt_template = """You are an expert financial analyst assistant. 
        Use the following context to answer the question. Be specific and cite numbers when available.
        
        Context: {context}
        
        Question: {question}
        
        Answer with specific numbers, dates, and metrics when available:"""
        
        self.QA_PROMPT = PromptTemplate(
            template=self.qa_prompt_template,
            input_variables=["context", "question"]
        )
        
        # Financial Report Prompt
        self.report_prompt_template = """You are an expert financial analyst creating a comprehensive financial analysis report.
        Using the context provided, create a detailed analysis report.
        
        Context: {context}
        
        Company/Period: {question}
        
        Create a comprehensive financial analysis report with these sections:
        
        **FINANCIAL STATEMENT ANALYSIS REPORT**
        
        **Executive Summary**
        • Overview of financial position and performance
        • Key highlights and concerns
        
        **Key Financial Ratios & Metrics**
        • EBITDA / Net Interest Expense
        • Total Debt / Adj. EBITDA  
        • Total Debt / Book Capitalization
        • Other relevant ratios from the documents
        
        **Income Statement Analysis**
        • Revenue trends and drivers
        • EBITDA/Operating margin analysis
        • Net income performance
        • Year-over-year comparisons
        
        **Cash Flow Analysis**
        • Operating cash flow trends
        • Free cash flow generation
        • Capital expenditure analysis
        • Dividend and financing activities
        
        **Balance Sheet Analysis**
        • Asset composition and quality
        • Leverage and debt metrics
        • Liquidity position
        
        **Risk Factors**
        • Key financial risks
        • Market and operational concerns
        
        **Outlook**
        • Overall assessment
        • Key metrics to monitor
        
        Use specific numbers and percentages from the documents. If data is not available for a section, note that briefly and continue.
        
        Report:"""
        
        self.REPORT_PROMPT = PromptTemplate(
            template=self.report_prompt_template,
            input_variables=["context", "question"]
        )
    
    def load_vector_store(self):
        """Load existing vector store"""
        try:
            if not Path(self.persist_directory).exists():
                logging.error(f"Vector store not found at {self.persist_directory}")
                return False
            
            # Load vector store
            self.vectorstore = Chroma(
                persist_directory=self.persist_directory,
                embedding_function=self.embeddings
            )
            
            # Create retrievers
            retriever_qa = self.vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 8}
            )
            
            retriever_report = self.vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 20}
            )
            
            # Create chains
            self.qa_chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=retriever_qa,
                return_source_documents=True,
                chain_type_kwargs={"prompt": self.QA_PROMPT}
            )
            
            self.report_chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=retriever_report,
                return_source_documents=True,
                chain_type_kwargs={"prompt": self.REPORT_PROMPT}
            )
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to load vector store: {e}")
            return False
    
    def query(self, question: str, mode: str = "Q&A") -> str:
        """Process query based on mode"""
        if not self.qa_chain or not self.report_chain:
            return "⚠️ System not initialized. Please run indexer.py first."
        
        try:
            if mode == "Q&A":
                result = self.qa_chain.invoke({"query": question})
            else:  # Report mode
                # Enhanced query for report generation
                report_query = f"Analyze financial data for: {question}. Gather all income statement, balance sheet, cash flow, and ratio data."
                result = self.report_chain.invoke({"query": report_query})
            
            # Get answer
            answer = result.get("result", "No answer generated")
            
            # Get sources
            sources = []
            for doc in result.get("source_documents", []):
                source = doc.metadata.get("source", "Unknown")
                page = doc.metadata.get("page", "")
                if source not in sources:
                    sources.append(source + (f" (Page {page})" if page else ""))
            
            # Add sources to answer
            if sources:
                answer += "\n\n📚 **Sources:** " + ", ".join(sources[:5])
            
            return answer
            
        except Exception as e:
            logging.error(f"Error: {e}")
            return f"⚠️ Error processing request: {str(e)}"