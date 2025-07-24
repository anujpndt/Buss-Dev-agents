import os
import csv
import json
import time
from typing import Annotated, Literal, List, Dict, Any, Set
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_tavily import TavilySearch
import pandas as pd
from pathlib import Path

# Enhanced rate limiting
last_request_time = 0
MIN_REQUEST_INTERVAL = 3
request_count = 0
MAX_REQUESTS_PER_MINUTE = 25

# API Keys
os.environ["TAVILY_API_KEY"] = "your_tavily_api_here"
os.environ["HUGGINGFACEHUB_API_TOKEN"] = "your_huggingface_api_here"
# Initialize LLM
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

try:
    print("🤗 Initializing Hugging Face model...")
    llm = HuggingFaceEndpoint(
        model="meta-llama/Llama-3.3-70B-Instruct",
        task="text-generation",
        provider="groq",
        temperature=0.1
    )
    model = ChatHuggingFace(llm=llm, verbose=True)
    print("✅ Hugging Face LLM initialized successfully")

except Exception as e:
    print(f"❌ LLM initialization failed: {e}")
    exit(1)

# Initialize Tavily tool
try:
    tavily_tool = TavilySearch(
        max_results=3,
        search_depth="advanced",
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        name="tavily_tool"
    )
    print("✅ Tavily tool initialized")
except Exception as e:
    print(f"❌ Tavily tool initialization failed: {e}")
    exit(1)

# Global variables
CSV_FILENAME = "2n8n-contact_research_report.csv"
SEARCH_QUERY = ""
LOCATION = ""
COMPANY_TYPE = ""
TARGET_COMPANIES = None
MAX_COMPANIES = 50

# Store discovered companies in workflow state
discovered_companies = []
current_research_index = 0
discovery_complete = False

def enhanced_rate_limit():
    """Enhanced rate limiting with better controls"""
    global last_request_time, request_count
    
    current_time = time.time()
    
    # Reset counter every minute
    if current_time - last_request_time > 60:
        request_count = 0
    
    # Check if we've hit the rate limit
    if request_count >= MAX_REQUESTS_PER_MINUTE:
        print("⏳ Rate limit reached, waiting 60 seconds...")
        time.sleep(60)
        request_count = 0
    
    # Ensure minimum interval between requests
    if current_time - last_request_time < MIN_REQUEST_INTERVAL:
        wait_time = MIN_REQUEST_INTERVAL - (current_time - last_request_time)
        time.sleep(wait_time)
    
    last_request_time = time.time()
    request_count += 1

def initialize_csv():
    """Initialize CSV file with headers"""
    global CSV_FILENAME
    
    print("📁 Initializing CSV file...")
    
    with open(CSV_FILENAME, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Company_Name", "Location", "Website", "Services", "Email", "Contact_Details", "Detailed_Report"])
    
    print("✅ CSV initialized with headers")

def add_company_to_csv(company_data):
    """Add company data to CSV"""
    global CSV_FILENAME
    
    try:
        with open(CSV_FILENAME, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                company_data.get('name', ''),
                company_data.get('location', ''),
                company_data.get('website', ''),
                company_data.get('services', ''),
                company_data.get('email', ''),
                company_data.get('contact_details', ''),
                company_data.get('detailed_report', '')
            ])
        
        print(f"✅ Added company to CSV: {company_data.get('name', 'Unknown')}")
        return True
        
    except Exception as e:
        print(f"❌ Error adding company to CSV: {e}")
        return False

def get_user_requirements():
    """Get user requirements for company research"""
    global TARGET_COMPANIES, SEARCH_QUERY, LOCATION, COMPANY_TYPE
    
    print("🎯 Defense Companies Research System")
    print("="*60)
    
    # Get company type/sector
    print("\n🏢 What type of defense companies are you looking for?")
    print("Examples: Defense software, Military contractors, Cybersecurity firms, etc.")
    
    while True:
        company_type = input("\nEnter company type/sector: ").strip()
        if company_type:
            COMPANY_TYPE = company_type
            break
        print("❌ Please enter a valid company type")
    
    # Get location preference
    print("\n🌍 Which location/region are you interested in?")
    print("Examples: India, United States, Global, Europe, etc.")
    
    while True:
        location = input("\nEnter location (or 'global' for worldwide): ").strip()
        if location:
            LOCATION = location
            break
        print("❌ Please enter a valid location")
    
    # Get number of companies
    while True:
        try:
            print(f"\n📊 How many {company_type} companies would you like to research?")
            print("   💡 Enter a positive number (or press Enter for unlimited, i.e., as many as can be found)")
            
            count_input = input("\nEnter number (or press Enter for unlimited): ").strip()
            
            if not count_input:
                TARGET_COMPANIES = float('inf')  # Use infinity for unlimited
                print("🔍 Mode: Find as many companies as possible (no limit)")
                break
            
            count = int(count_input)
            
            if count < 1:
                print("❌ Please enter a positive number")
                continue
            
            TARGET_COMPANIES = count
            break
            
        except ValueError:
            print("❌ Please enter a valid number or press Enter")
            continue
        except KeyboardInterrupt:
            print("\n👋 Research cancelled")
            exit(0)
    
    # Generate search query
    if LOCATION.lower() == "global":
        SEARCH_QUERY = f"top {company_type} companies worldwide"
    else:
        SEARCH_QUERY = f"major {company_type} companies in {LOCATION}"
    
    print(f"\n✅ Configuration:")
    print(f"   🏢 Company Type: {COMPANY_TYPE}")
    print(f"   🌍 Location: {LOCATION}")
    print(f"   📊 Target Count: {TARGET_COMPANIES}")
    print(f"   🔍 Search Query: {SEARCH_QUERY}")
    
    return True

@tool
def add_discovered_company(company_name: str, location: str = "", website: str = "", services: str = "", email: str = "", contact_details: str = "") -> str:
    """Add a discovered company to the list"""
    global discovered_companies, TARGET_COMPANIES
    
    if not company_name or not company_name.strip():
        return "Error: Company name is required"
    
    # Stop if we've reached the target
    if len(discovered_companies) >= TARGET_COMPANIES:
        return f"Target reached: {TARGET_COMPANIES} companies found"
    
    # Check for duplicates (case-insensitive)
    company_name_clean = company_name.strip().lower()
    for existing in discovered_companies:
        if existing['name'].lower().strip() == company_name_clean:
            return f"Company {company_name} already exists"
    
    company_data = {
        'name': company_name.strip(),
        'location': location.strip(),
        'website': website.strip(),
        'services': services.strip(),
        'email': email.strip(),
        'contact_details': contact_details.strip(),
        'detailed_report': ''
    }
    
    discovered_companies.append(company_data)
    
    print(f"📝 Added company {len(discovered_companies)}: {company_name}")
    
    # Check if we've reached the target
    if len(discovered_companies) >= TARGET_COMPANIES:
        return f"SUCCESS: Found {len(discovered_companies)} companies (target reached)"
    
    return f"Successfully added company: {company_name}"

def create_discovery_agent():
    """Create discovery agent with focused prompt"""
    print("�� Creating Discovery Agent...")
    
    # Get the actual tool name
    tool_name = tavily_tool.name if hasattr(tavily_tool, 'name') else 'TavilySearch'
    
    discovery_agent = create_react_agent(
        model,
        tools=[tavily_tool, add_discovered_company],
        prompt=f"""IMPORTANT: You must only call one tool per turn. Never output more than one <function=...> call in a single response.
        IMPORTANT: You must only call one tool per turn. Never output Python code, import statements, or requests. Only use the provided tools/functions (e.g., {tool_name}, add_discovered_company). Do not output anything except tool/function calls in the required format.
You are a Company Discovery Agent. Find exactly {TARGET_COMPANIES} companies of type "{COMPANY_TYPE}" in "{LOCATION}".

OBJECTIVE: Find exactly {TARGET_COMPANIES} companies and stop when target is reached.

PROCESS:
1. Search using the {tool_name} tool with query: "{SEARCH_QUERY}"
2. Extract company information from results
3. For each company, find contact details of key personnel
4. Use add_discovered_company for each company with: name, location, website, services, email, contact_details
5. STOP when you reach {TARGET_COMPANIES} companies

EMAIL FIELD (PRIORITY ORDER):
For the email field, search for and prioritize in this order:
1. CEO email address
2. President email address  
3. Director email address
4. Business Development team email address
5. Company general email address

EMAIL SEARCH INSTRUCTIONS:
- Search for \"[Company Name] CEO email contact\"
- Search for \"[Company Name] president email contact\"
- Search for \"[Company Name] director email contact\"
- Search for \"[Company Name] business development email contact\"
- Search for \"[Company Name] contact email\"

CONTACT DETAILS SEARCH:
For each company, search for key personnel contact information:
- CEO contact details (email, phone, LinkedIn profile URL)
- President contact details (email, phone, LinkedIn profile URL)
- Director contact details (email, phone, LinkedIn profile URL)
- Business Development team contact details (email, phone, LinkedIn profile URL)

CONTACT DETAILS FORMAT:
Format contact details as:
\"CEO: [Name] - Email: [email] - LinkedIn: [url]
President: [Name] - Email: [email] - LinkedIn: [url]
Director: [Name] - Email: [email] - LinkedIn: [url]
Business Development Team: [Name] - Email: [email] - LinkedIn: [url]
Company Email: [general_email]\"

If you cannot find key personnel details, at minimum provide:
\"Company Email: [general_company_email]\"

IMPORTANT:
- The email field should contain the BEST single email address you can find (CEO > President > Director > Business Development > Company)
- Search efficiently to find companies quickly
- Extract complete information: name, location, website, services, email, contact_details
- For contact_details, prioritize CEO, President, Director, or Business Development team
- If no key personnel found, include company general email
- Add each company immediately using add_discovered_company
- Stop when target is reached
- Focus on quality over quantity

Start searching now."""
    )

    print("✅ Discovery Agent created successfully")
    return discovery_agent

def create_research_agent():
    """Create research agent with sequential search approach"""
    print("🔬 Creating Research Agent...")

    research_agent = create_react_agent(
        model,
        tools=[tavily_tool,add_discovered_company],
        prompt=f"""IMPORTANT: You must only call one tool per turn. Never output more than one <function=...> call in a single response.
        IMPORTANT: You must only call one tool per turn. Never output Python code, import statements, or requests. Only use the provided tools/functions (e.g., tavily_tool, add_discovered_company). Do not output anything except tool/function calls in the required format.
You are a Research Agent. Create comprehensive reports for {COMPANY_TYPE} companies.

RESEARCH PROCESS:
1. Use tavily_tool ONE search at a time (not multiple simultaneous searches)
2. Search sequentially with these queries:
   - \"[Company Name] overview defense government military projects\"
   - \"[Company Name] AI technology capabilities services\"
   - \"[Company Name] leadership team contact information\"

REPORT STRUCTURE:
** Company Overview:**
- Company background and founding
- Headquarters and locations
- Business focus and specializations
- SOURCE [URL]

** Past & Flagship Projects:**
**Defense Software Systems:**
- **Project 1:** [Search for a detailed description, challenges faced, technology used, timeline, and client/partner info for each project]
- **Project 2:** [Provide detailed project descriptions, addressing challenges, goals, and technology used]
- **Project 3:** [Include detailed analysis of impact, client info, and outcome]

**Government Solutions:**
- **Project 1:** [Search for government-related solutions provided by the company. Include detailed description and background]
- **Project 2:** [Include implementation details, beneficiaries, and related technologies used]
- **Project 3:** [Include all related government collaborations or contracts]

**Military Applications:**
- **Project 1:** [Look for military-related projects the company is involved in. Provide technology and operational details]
- **Project 2:** [Provide comprehensive details of military-focused projects]
- **Project 3:** [Include in-depth information on military technologies and the company's role in defense projects]

**Source Links:** [For each project, provide detailed sources such as LinkedIn, Medium, credible defense portals]


** Recent & Ongoing Focus Areas:**

**Technology Advancement:**
- **Technology 1:** [Research recent advancements, including R&D and breakthroughs. Mention specific technologies and innovations]
- **Technology 2:** [Look for new tech the company has developed or partnered with, supported by industry sources]
- **Technology 3:** [Provide insights into their technological edge, especially in AI, defense, or security]


**Strategic Partnerships & Collaborations:**
- **Partner 1:** [Search for partnerships with other companies, provide details on joint ventures, objectives, and projects]
- **Partner 2:** [Look for partnerships in defense, security, or government projects and provide related information]
- **Partner 3:** [Identify strategic collaborations and the scope of each collaboration]

**Source Links:** [Ensure you reference reputable business news sources or official press releases for each collaboration]

** Software & Tools – Comprehensive Summary:**
- **Tool 1:** [Search for details on any software products the company develops, including capabilities, use cases, and target users]
- **Tool 2:** [Look for tools related to the company's defense or AI offerings. Provide detailed descriptions and reviews]
- **Tool 3:** [Research the platforms or systems the company develops, including technical specifications, deployment models, and competitive advantages]
- SOURCE [URL]

** Leadership & Contact:**
- Key executives and leadership
- Contact information
- Website and online presence
- SOURCE [URL]

IMPORTANT:
- STRICTLY mention source url from where you extracting the information 
- Detailed Explanation of the project like what they address, technologies used, how it works and any other additional information 
- Use tavily_tool ONE search at a time
- Wait for results before next search
- Create detailed but concise reports
- Focus on defense/government/military aspects

Start researching the given company now."""
    )

    print("✅ Research Agent created successfully")
    return research_agent


def discovery_node(state: MessagesState):
    """Discovery node - find companies and add them to discovered_companies list"""
    print("\n" + "="*50)
    print("🔍 DISCOVERY NODE ACTIVATED")
    print("="*50)

    global discovery_complete

    # Check if we already have enough companies
    if len(discovered_companies) >= TARGET_COMPANIES:
        discovery_complete = True
        print(f"✅ Discovery already complete. Found {len(discovered_companies)} companies")
        return {
            "messages": [HumanMessage(content=f"DISCOVERY_COMPLETE")]
        }

    try:
        enhanced_rate_limit()
        discovery_agent = create_discovery_agent()
        print(f"�� Starting discovery process...")

        # Add safety counter
        max_attempts = 10
        attempts = 0
        
        while len(discovered_companies) < TARGET_COMPANIES and attempts < max_attempts:
            attempts += 1
            print(f"🔍 Discovery attempt {attempts}/{max_attempts}")
            
            discovery_instruction = (
                f"Find one {COMPANY_TYPE} company in {LOCATION} that is not already in the list. "
                "Use the search tool to search and add_discovered_company to save the company. "
                "Stop if you cannot find more unique companies."
            )
            
            result = discovery_agent.invoke({"messages": [HumanMessage(content=discovery_instruction)]})
            
            # Check if agent found a company
            if isinstance(result, dict) and result.get("messages"):
                last_message = str(result["messages"][-1].content)
                if "Target reached" in last_message or "SUCCESS" in last_message:
                    break
                if "already exists" in last_message:
                    print("⚠️ Duplicate company found, continuing...")
                    continue
            
            # Safety break if no progress
            if attempts >= max_attempts:
                print("⚠️ Maximum discovery attempts reached")
                break

        companies_found = len(discovered_companies)
        discovery_complete = True
        print(f"✅ Discovery completed. Found {companies_found} companies")

        return {
            "messages": [HumanMessage(content=f"DISCOVERY_COMPLETE")]
        }

    except Exception as e:
        error_msg = f"Discovery error: {str(e)}"
        print(f"❌ {error_msg}")
        import traceback
        traceback.print_exc()  # Add this for debugging
        return {
            "messages": [HumanMessage(content=f"DISCOVERY_ERROR: {error_msg}")]
        }
def research_node(state: MessagesState):
    """Research node - research companies one by one and add to CSV"""
    print("\n" + "="*50)
    print("🔬 RESEARCH NODE ACTIVATED")
    print("="*50)

    global current_research_index

    try:
        enhanced_rate_limit()

        if current_research_index >= len(discovered_companies):
            print("🎉 All companies researched!")
            return {
                "messages": [HumanMessage(content="ALL_RESEARCH_COMPLETE")]
            }

        # Get current company to research
        current_company = discovered_companies[current_research_index]
        company_name = current_company['name']

        print(f"🔍 Researching company {current_research_index + 1}/{len(discovered_companies)}: {company_name}")

        research_agent = create_research_agent()

        # Simple research instruction
        research_instruction = f"Research '{company_name}' and create a detailed report. Use tavily_tool to search for information about this company."
        result = research_agent.invoke({"messages": [HumanMessage(content=research_instruction)]})

        # Get the research report
        research_report = result["messages"][-1].content

        # Update company data with research report
        current_company['detailed_report'] = research_report

        # Add to CSV
        add_company_to_csv(current_company)

        print(f"✅ Research completed for: {company_name}")

        # Move to next company
        current_research_index += 1

        return {
            "messages": [HumanMessage(content=f"RESEARCH_PROGRESS")]
        }

    except Exception as e:
        error_msg = f"Research error: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "messages": [HumanMessage(content=f"RESEARCH_ERROR: {error_msg}")]
        }


def should_continue(state: MessagesState) -> Literal["research", END]:
    """Determine workflow next step"""
    print("\n🤖 WORKFLOW DECISION POINT")
    
    last_message = state["messages"][-1].content
    
    # Check if all research is complete
    if "ALL_RESEARCH_COMPLETE" in last_message:
        print("➡️ DECISION: ENDING workflow - All research complete")
        return END
    
    # Check if we have errors
    if "ERROR" in last_message:
        print("➡️ DECISION: ENDING workflow - Error occurred")
        return END
    
    # Check if discovery is complete and we have companies to research
    if "DISCOVERY_COMPLETE" in last_message and len(discovered_companies) > 0:
        print("➡️ DECISION: Moving to RESEARCH phase")
        return "research"
    
    # Check if we're in middle of research
    if "RESEARCH_PROGRESS" in last_message and current_research_index < len(discovered_companies):
        print(f"➡️ DECISION: Continue RESEARCH phase - {current_research_index}/{len(discovered_companies)} completed")
        return "research"
    
    # Check if research is complete
    if current_research_index >= len(discovered_companies) and len(discovered_companies) > 0:
        print("➡️ DECISION: ENDING workflow - Research complete")
        return END
    
    # Default: end workflow
    print("➡️ DECISION: ENDING workflow - Default")
    return END

def run_enhanced_research():
    """Run the enhanced research workflow"""
    global discovered_companies, current_research_index, discovery_complete
    
    # Reset global state
    discovered_companies = []
    current_research_index = 0
    discovery_complete = False
    
    try:
        # Get user requirements
        if not get_user_requirements():
            return False
        
        # Initialize CSV
        initialize_csv()
        
        # Create workflow
        workflow = StateGraph(MessagesState)
        
        # Add nodes
        workflow.add_node("discovery", discovery_node)
        workflow.add_node("research", research_node)
        
        # Add edges
        workflow.add_edge(START, "discovery")
        workflow.add_conditional_edges(
            "discovery",
            should_continue,
            {
                "research": "research",
                END: END
            }
        )
        workflow.add_conditional_edges(
            "research",
            should_continue,
            {
                "research": "research",
                END: END
            }
        )
        
        # Compile workflow
        graph = workflow.compile()
        
        print(f"\n🎯 Starting research for {TARGET_COMPANIES} companies...")
        
        start_time = time.time()
        
        # Run the workflow
        initial_state = {
            "messages": [HumanMessage(content="Starting research workflow")]
        }
        
        print("\n🔄 Starting workflow execution...")
        final_state = graph.invoke(initial_state, {"recursion_limit": 50})
        
        end_time = time.time()
        
        # Display results
        print("\n" + "="*80)
        print("🎉 RESEARCH WORKFLOW COMPLETED!")
        print("="*80)
        
        if os.path.exists(CSV_FILENAME):
            df = pd.read_csv(CSV_FILENAME)
            row_count = len(df)
            
            print(f"\n📊 FINAL RESULTS:")
            print(f"   📄 File: {CSV_FILENAME}")
            print(f"   🏢 Companies researched: {row_count}")
            target_display = "Unlimited" if TARGET_COMPANIES == float('inf') else TARGET_COMPANIES
            print(f"   🎯 Target: {target_display}")
            print(f"   ⏱️ Time taken: {end_time - start_time:.1f} seconds")
            
            return True
        else:
            print("❌ No results file found")
            return False
            
    except Exception as e:
        print(f"❌ Workflow Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up global state
        discovered_companies = []
        current_research_index = 0
        discovery_complete = False

if __name__ == "__main__":
    success = run_enhanced_research()
    
    if success:
        print(f"\n🎉 RESEARCH COMPLETED SUCCESSFULLY!")
        print(f"📄 Results saved to: {CSV_FILENAME}")
        print(f"🏢 Researched {len(discovered_companies)} {COMPANY_TYPE} companies from {LOCATION}")
        print("\n✨ FEATURES WORKING:")
        print("   ✅ Discovery Agent - Finds companies with complete info including contact details")
        print("   ✅ Research Agent - Creates comprehensive reports")
        print("   ✅ Sequential workflow - Discovery → Research → CSV")
        print("   ✅ Context management - Avoids length issues")
        print("   ✅ Complete CSV output - All required fields including contact details")
        print("   ✅ Contact Details - CEO, President, Director, Business Development team info")
        print("   ✅ Email Column - Key personnel email or company email")
        print(f"\n📁 Open '{CSV_FILENAME}' to view detailed results!")
    else:
        print("\n❌ Research failed. Please check the errors above.")