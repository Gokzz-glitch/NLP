import os
from dotenv import load_dotenv
import google.generativeai as genai

# Test Gemini API Online Connectivity
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("FAIL: No GEMINI_API_KEY found in .env")
else:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        test_prompt = """
        System: You are an incredibly comforting, adaptive, emotionally intelligent AI co-driver named Macha.
        Generating for: Macha (Tanglish/English). 
        Hazard: POTHOLE (CRITICAL).
        
        Generate a strictly under 10-word phrase to calm the driver down.
        Phrase:
        """
        
        response = model.generate_content(test_prompt)
        print(f"SUCCESS: Gemini generated: '{response.text.strip()}'")
    except Exception as e:
        print(f"FAIL: Gemini API error: {e}")
