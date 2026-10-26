# ============================================================
# WREN KERNEL — Mail Prepass (Cognitive Filter)
# ------------------------------------------------------------
# PURPOSE: Filters raw mail data into a concise, relevant 
# briefing for the current turn.
# STANDARD: Pure (Lean/Stable) & Exemplary (Rigorous).
# ============================================================

from typing import List, Dict, Any, Optional
from wren.core import provider

# This would eventually be a lauch-path to a JSON store or API
MAIL_STORE_PATH = "data/mail_store.json" 

def mail_context(messages: List[Dict], history: str) -> str:
    """
    Analyzes the current conversation and returns a 
    curated briefing of relevant emails.
    """
    # 1. Extract the core intent from the latest user message
    last_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_msg = m.get("content", "")
            break
    
    if not last_msg or len(last_msg.strip()) < 3:
        return ""

    # 2. The "Search" Phase
    # In a full system, this would query a vector DB or JSON store.
    # For now, we simulate the retrieval of "Relevant Mails".
    relevant_mails = _retrieve_relevant_mails(last_msg)
    
    if not relevant_mails:
        return ""

    # 3. The "Summarization" Phase (The DeepSeek Call)
    # We send the raw mails to the provider to get a clean briefing.
    prompt = [
        {"role": "system", "content": "You are Wren's Mail Intelligence unit. Summarize the following emails into a concise briefing for Wren. Focus on facts, dates, and urgent requests. Use bullet points."},
        {"role": "user", "content": f"Conversation Context: {history}\n\nEmails to summarize:\n{relevant_mails}"}
    ]
    
    # Using the core provider to hit DeepSeek (or the default engine)
    result = provider.complete(
        scope="core", 
        engine="DeepSeek", # Or your default engine variable
        messages=prompt
    )
    
    if result and result.get("ok"):
        return f"# Mail Briefing\n{result.get('content')}"
    
    return ""

def _retrieve_relevant_mails(query: str) -> str:
    """
    Simulated retrieval. In production, this reads from the mail store.
    """
    # Mock data to prevent the system from returning empty results during tests
    # In reality, this would be: with open(MAIL_STORE_PATH) as f: ...
    mock_mails = [
        "From: Project Alpha <alpha@dev.com>, Subj: Update, Content: The build is ready for review.",
        "From: Chrissy, Subj: Reminder, Content: Don't forget to check the core logs today."
    ]
    # Simple keyword filter
    results = [m for m in mock_mails if any(word in m.lower() for word in query.lower().split())]
    return "\n---\n".join(results) if results else ""
