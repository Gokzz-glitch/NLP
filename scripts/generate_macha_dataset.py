import os
import json
import logging
import time
from dotenv import load_dotenv
import google.generativeai as genai

# [PERSONA 4: DATASET GENERATOR - TEACHER]

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: [GEN_DATASET] %(message)s")

class MachaDatasetGenerator:
    def __init__(self, scenarios_path="data/scenarios.json", output_path="data/macha_training_data.jsonl"):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.scenarios_path = os.path.join(base_dir, scenarios_path)
        self.output_path = os.path.join(base_dir, output_path)
        
        if not api_key:
            raise ValueError("No GEMINI_API_KEY found in .env")
            
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')

    def generate_example(self, scenario):
        prompt = f"""
        System: You are an incredibly comforting, adaptive, emotionally intelligent AI co-driver named Macha.
        Generating for: Macha (Tanglish/English/Tamil/Hindi/Kannada). 

        Scenario Context: {scenario.get('context')}
        Hazard Type: {scenario.get('type')}
        Severity: {scenario.get('severity')}

        Generate a strictly under 10-word phrase to calm the driver down and alert them.
        Return ONLY the spoken phrase. No thinking text.
        Phrase:
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logging.error(f"GEN_ERROR for {scenario['id']}: {e}")
            return None

    def run(self):
        with open(self.scenarios_path, 'r') as f:
            scenarios = json.load(f)['scenarios']

        logging.info(f"STARTING_DATASET_GENERATION: {len(scenarios)} scenarios.")
        count = 0
        
        # Ensure 'data' directory exists
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        
        with open(self.output_path, 'a', encoding='utf-8') as out_f:
            for scenario in scenarios:
                phrase = self.generate_example(scenario)
                if phrase:
                    # Format as JSONL for LLM FT
                    entry = {
                        "instruction": f"Alert driver for {scenario['type']} with {scenario['severity']} severity in context: {scenario['context']}",
                        "context": "Driver is on the road in Chennai environment.",
                        "response": phrase
                    }
                    out_f.write(json.dumps(entry) + "\n")
                    count += 1
                    logging.info(f"GENERATED: [{scenario['id']}] -> '{phrase}'")
                
                # Respect API limits
                time.sleep(1)

        logging.info(f"SUCCESS: Generated {count} synthetic examples for Macha local fine-tuning.")

if __name__ == "__main__":
    generator = MachaDatasetGenerator()
    generator.run()
