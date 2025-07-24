import os
import pandas as pd
from pathlib import Path
from langchain_community.document_loaders import PyMuPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from tqdm import tqdm
import time

def check_file_exists(file_path):
    """Check if file exists and return absolute path"""
    if os.path.exists(file_path):
        return os.path.abspath(file_path)
    else:
        print(f"Warning: File {file_path} not found")
        return None

def load_documents_safely(file_paths):
    """Load documents with error handling"""
    docs = []
    successful_loads = []
    
    for file_path in file_paths:
        abs_path = check_file_exists(file_path)
        if abs_path:
            try:
                loader = PyMuPDFLoader(abs_path)
                loaded_docs = loader.load()
                docs.extend(loaded_docs)
                successful_loads.append(file_path)
                print(f"✓ Successfully loaded: {file_path}")
            except Exception as e:
                print(f"✗ Failed to load {file_path}: {str(e)}")
        else:
            print(f"✗ File not found: {file_path}")
    
    return docs, successful_loads

def setup_rag_system():
    """Set up the complete RAG system"""
    
    # === 1. Load documents ===
    print("=== Loading Documents ===")
    
    # Define file paths - update these to match your actual file locations
    file_paths = [
        "AI_Projects.pdf",
        "IDEA.AI.pdf", 
        "IDEA_Foundation_Big_Data_AI_Solutions.docx.pdf",
    ]
    
    # Alternative: Look for PDFs in current directory
    current_dir = Path(".")
    pdf_files = list(current_dir.glob("*.pdf"))
    
    if not any(os.path.exists(f) for f in file_paths) and pdf_files:
        print("Original files not found. Using PDFs found in current directory:")
        file_paths = [str(f) for f in pdf_files]
        for f in file_paths:
            print(f"  - {f}")
    
    docs, successful_loads = load_documents_safely(file_paths)
    
    if not docs:
        print("No documents loaded. Please check file paths.")
        return None
    
    print(f"Total documents loaded: {len(docs)}")
    
    # === 2. Split into Chunks ===
    print("\n=== Splitting Documents ===")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, 
        chunk_overlap=200,
        length_function=len,
        separators=["\n\n", "\n", " ", ""]
    )
    chunks = splitter.split_documents(docs)
    print(f"Total chunks created: {len(chunks)}")
    
    # === 3. Embeddings ===
    print("\n=== Creating Embeddings ===")
    embedding_model = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    
    # Create vector database
    vectordb = Chroma.from_documents(
        documents=chunks, 
        embedding=embedding_model, 
        persist_directory="./collab_rag_db"
    )
    retriever = vectordb.as_retriever(search_kwargs={"k": 5})
    
    # === 4. LLM with Groq ===
    print("\n=== Setting up LLM ===")
    try:
        llm = ChatGroq(
            model_name="llama-3.1-8b-instant",
            temperature=0.1  # Lower temperature for more consistent business analysis
        )
    except Exception as e:
        print(f"Error setting up Groq LLM: {e}")
        print("Make sure you have set your GROQ_API_KEY environment variable")
        return None
    
    # === 5. Enhanced Prompt Template ===
    prompt_template = PromptTemplate(
    input_variables=["context", "question"],
    template="""
You are a senior strategic partnership consultant with years of experience in technology collaborations, M&A advisory, and cross-industry partnerships. Your expertise spans defense technology, AI integration, and international business development.
Strategic Partnership Evaluation for IDEA Foundation

INTERNAL COMPANY PROFILE & CAPABILITIES MENTION All of them:
{context}

EXTERNAL COMPANY DETAILED ANALYSIS:
{question}

PARTNERSHIP ASSESSMENT FRAMEWORK:

Analyze the partnership potential using a comprehensive evaluation methodology. For each opportunity, provide specific reasoning, evidence from the company data, and quantifiable benefits where possible.

### Opportunity Identification:

For each company, identify 3 potential collaboration opportunities based on their **services**, **products**, or **solutions**. Focus on how these offerings align with IDEA Foundation’s capabilities.

**Opportunity Format:**
1. **Service/Product Name**:
   - **Description**: [Describe the specific product, service, or solution they offer]
   - **Reason for Match with IDEA Foundation**: [Explain why this offering aligns with IDEA Foundation's capabilities and goals]
   - **Scope of Collaboration**: [How can Both companies integrate with, enhance, or benefit from this solution?]
   - **Quantifiable Benefits**: [What specific value or impact will this collaboration bring? Include market potential or technical advantages]
   - **Score**: [A score based on the relevance, feasibility, and potential of this collaboration]

2. **Service/Product Name**: 
   - [Same format as above]

3. **Service/Product Name**:
   - [Same format as above]

---

### Additional Guidelines:
- For each **service/product/solution** identified, ensure that the **reason for the match with IDEA Foundation** is clearly explained.
- **Quantifiable benefits** should be backed with any available data such as market size, growth opportunities, or technical improvements.
- **Score**: Provide a score from 1-10, where 1 is low potential and 10 is high potential for collaboration, based on strategic alignment and impact.
- STRICTLY Elaborate each field of the opportunities and other field 
- Focus on **specific solutions** the company offers and ensure they are actionable for collaboration."""
    )
    
    # === 6. RAG Chain ===
    rag_chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": prompt_template},
        return_source_documents=False  # Don't return source docs for batch processing
    )
    
    return rag_chain, vectordb

def create_company_description(row, text_columns):
    """Create a comprehensive company description focusing on Full Detailed Report"""
    
    # Prioritize Full Detailed Report as the main source
    detailed_report = ""
    company_name = ""
    services_desc = ""
    
    # Extract key information
    if 'Full Detailed Report' in row and pd.notna(row['Full Detailed Report']):
        detailed_report = str(row['Full Detailed Report']).strip()
    
    if 'Company_Name' in row and pd.notna(row['Company_Name']):
        company_name = str(row['Company_Name']).strip()
    
    if 'Services/Description' in row and pd.notna(row['Services/Description']):
        services_desc = str(row['Services/Description']).strip()
    
    # Build comprehensive company profile
    company_profile = f"""
COMPANY: {company_name}

SERVICES OVERVIEW: {services_desc}

DETAILED COMPANY REPORT:
{detailed_report}

ADDITIONAL CONTEXT:
"""
    
    # Add any other relevant columns
    for col in text_columns:
        if col not in ['Company_Name', 'Services/Description', 'Full Detailed Report']:
            if col in row and pd.notna(row[col]) and str(row[col]).strip():
                company_profile += f"{col}: {str(row[col]).strip()}\n"
    
    return company_profile.strip()

def analyze_single_company(rag_chain, company_description, company_name="Unknown"):
    """Analyze collaboration potential with a single company"""
    
    try:
        result = rag_chain.invoke({"query": company_description})
        return result['result']
        
    except Exception as e:
        error_msg = f"Error analyzing {company_name}: {str(e)}"
        print(error_msg)
        return f"Analysis failed: {str(e)}"

def process_csv_batch(csv_file_path, output_file_path=None, text_columns=None, 
                     collaboration_column_name="Collaboration_Analysis"):
    """Process CSV file with multiple companies and generate RAG analysis"""
    
    print(f"\n=== Processing CSV: {csv_file_path} ===")
    
    # Check if CSV exists
    if not os.path.exists(csv_file_path):
        print(f"Error: CSV file {csv_file_path} not found")
        return None
    
    # Load CSV
    try:
        df = pd.read_csv(csv_file_path)
        print(f"✓ Loaded CSV with {len(df)} rows and {len(df.columns)} columns")
        print(f"Columns: {list(df.columns)}")
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return None
    
    # Auto-detect text columns if not specified
    if text_columns is None:
        text_columns = []
        for col in df.columns:
            # Include columns that are likely to contain meaningful text
            if df[col].dtype == 'object' and col.lower() not in ['id', 'index']:
                sample_text = str(df[col].iloc[0]) if not df[col].empty else ""
                if len(sample_text) > 10:  # Only include columns with substantial text
                    text_columns.append(col)
        print(f"Auto-detected text columns: {text_columns}")
    
    if not text_columns:
        print("No suitable text columns found for analysis")
        return None
    
    # Setup RAG system
    rag_system = setup_rag_system()
    if not rag_system:
        print("Failed to setup RAG system")
        return None
    
    rag_chain, vectordb = rag_system
    
    # Create output filename if not provided
    if output_file_path is None:
        base_name = os.path.splitext(csv_file_path)[0]
        output_file_path = f"{base_name}_with_analysis.csv"
    
    # Check if collaboration column already exists
    if collaboration_column_name in df.columns:
        print(f"Warning: Column '{collaboration_column_name}' already exists. It will be overwritten.")
    
    # Initialize the analysis column
    df[collaboration_column_name] = ""
    
    # Process each company
    print(f"\n=== Analyzing {len(df)} companies ===")
    
    for index, row in tqdm(df.iterrows(), total=len(df), desc="Processing companies"):
        # Create company description
        company_description = create_company_description(row, text_columns)
        
        # Get company name for logging (assume first column or 'name' column)
        company_name = str(row.iloc[0]) if len(row) > 0 else f"Row {index}"
        if 'name' in df.columns:
            company_name = str(row['name'])
        elif 'company' in df.columns:
            company_name = str(row['company'])
        elif 'company_name' in df.columns:
            company_name = str(row['company_name'])
        
        # Analyze collaboration potential
        analysis = analyze_single_company(rag_chain, company_description, company_name)
        
        # Store the analysis
        df.at[index, collaboration_column_name] = analysis
        
        # Add small delay to avoid rate limiting
        time.sleep(0.5)
        
        # Save progress every 10 companies
        if (index + 1) % 10 == 0:
            try:
                df.to_csv(output_file_path, index=False)
                print(f"Progress saved: {index + 1}/{len(df)} companies processed")
            except Exception as e:
                print(f"Warning: Could not save progress: {e}")
    
    # Save final results
    try:
        df.to_csv(output_file_path, index=False)
        print(f"\n✓ Analysis complete! Results saved to: {output_file_path}")
        print(f"✓ Processed {len(df)} companies")
        print(f"✓ Added column: {collaboration_column_name}")
        return df
        
    except Exception as e:
        print(f"Error saving results: {e}")
        return df

def main():
    """Main function to run the CSV batch processing"""
    
    print("=== Enhanced CSV Batch RAG Analysis System ===")
    print("Optimized for detailed company reports with comprehensive partnership analysis.")
    
    # Configuration for your specific CSV format
    csv_file_path = "E-contact_research_report.csv"  # Your CSV file
    output_file_path = "E-contact_analyzed_companies.csv"  # Output file
    
    # Your CSV columns - Full Detailed Report is the primary analysis source
    text_columns = ['Company_Name', 'Services/Description', 'Full Detailed Report', 'City and Country', 'Website URL']
    collaboration_column_name = "Strategic_Partnership_Analysis"
    
    print(f"Processing CSV: {csv_file_path}")
    print(f"Primary analysis column: Full Detailed Report")
    print(f"Supporting columns: {[col for col in text_columns if col != 'Full Detailed Report']}")
    print(f"Output file: {output_file_path}")
    
    # Process the CSV
    result_df = process_csv_batch(
        csv_file_path=csv_file_path,
        output_file_path=output_file_path,
        text_columns=text_columns,
        collaboration_column_name=collaboration_column_name
    )
    
    if result_df is not None:
        print("\n=== Sample Results ===")
        # Show first company analysis (truncated for display)
        sample_analysis = result_df[collaboration_column_name].iloc[0]
        print(f"Company: {result_df['Company_Name'].iloc[0]}")
        print(f"Analysis Preview: {sample_analysis[:500]}...")
        
        # Show statistics
        analysis_col = collaboration_column_name
        if analysis_col in result_df.columns:
            non_empty = result_df[analysis_col].notna().sum()
            print(f"\nSuccessfully analyzed: {non_empty}/{len(result_df)} companies")
    
    else:
        print("Batch processing failed. Please check your files and configuration.")




if __name__ == "__main__":
    # Run the main interactive function
    main()
    
    # Uncomment below to run example
    # example_usage()