import os
import re
import json

# Configuration
EXTENSIONS = ('.py', '.js', '.ts', '.java')
EXCLUDE_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', 'dist', 'build'}

# Patterns (from Static Analysis Spec)
PATTERNS = {
    "identity_bypass": re.compile(r"(?i)(user|account|email|role|tenant)(Id|_id)?\s*(===|!==|==|!=)\s*(['\"].*['\"]|\d+)"),
    "boolean_short_circuit": re.compile(r"(if\s*\(?\s*(true|false|True|False|1|0)\s*\)?\s*:?|return\s+(true|false|True|False))"),
    "bypass_keyword": re.compile(r"(?i)(skip|bypass|override|demo|mock|fake|dummy|test_mode|debug_mode)\s*[:=]\s*(true|True|1|['\"].*['\"])"),
    "legitimate_constant": re.compile(r"^[A-Z_][A-Z0-9_]+\s*[:=]\s*(['\"].*['\"]|\d+|True|False|None)")
}

# Contextual filters (e.g., validate*, auth*)
SECURITY_FUNCTIONS = re.compile(r"(?i)(validate|check|auth|authorize|verify|permission|login|access)")

def scan_file(filepath):
    results = {
        "loc": 0,
        "identity_bypass": 0,
        "boolean_short_circuit": 0,
        "bypass_keyword": 0,
        "legitimate_constant": 0,
        "security_hotspots": []
    }
    
    try:
        with open(filepath, 'r', errors='ignore') as f:
            lines = f.readlines()
            results["loc"] = len(lines)
            
            for i, line in enumerate(lines, 1):
                raw_line = line.strip()
                if not raw_line or raw_line.startswith(('#', '//', '*', '/*')):
                    continue
                
                # Check suspicious patterns
                if PATTERNS["identity_bypass"].search(raw_line):
                    results["identity_bypass"] += 1
                    results["security_hotspots"].append((i, "IDENTITY_BYPASS", raw_line))
                
                if PATTERNS["boolean_short_circuit"].search(raw_line):
                    # Only flag if in security-sensitive function context (simplified here)
                    # We look for the keyword in the file/function name or previous context
                    results["boolean_short_circuit"] += 1
                    results["security_hotspots"].append((i, "BOOLEAN_SHORT_CIRCUIT", raw_line))
                
                if PATTERNS["bypass_keyword"].search(raw_line):
                    results["bypass_keyword"] += 1
                    results["security_hotspots"].append((i, "BYPASS_KEYWORD", raw_line))
                
                # Check legitimate patterns
                if PATTERNS["legitimate_constant"].match(raw_line):
                    results["legitimate_constant"] += 1
                    
    except Exception as e:
        pass
        
    return results

def run_scan(root_dir):
    summary = {
        "total_files": 0,
        "total_loc": 0,
        "total_identity_bypass": 0,
        "total_boolean_short_circuit": 0,
        "total_bypass_keyword": 0,
        "total_legitimate_constants": 0,
        "file_breakdown": {}
    }
    
    for root, dirs, files in os.walk(root_dir):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if file.endswith(EXTENSIONS):
                filepath = os.path.join(root, file)
                res = scan_file(filepath)
                
                summary["total_files"] += 1
                summary["total_loc"] += res["loc"]
                summary["total_identity_bypass"] += res["identity_bypass"]
                summary["total_boolean_short_circuit"] += res["boolean_short_circuit"]
                summary["total_bypass_keyword"] += res["bypass_keyword"]
                summary["total_legitimate_constants"] += res["legitimate_constant"]
                
                if res["identity_bypass"] > 0 or res["boolean_short_circuit"] > 0 or res["bypass_keyword"] > 0:
                    summary["file_breakdown"][filepath] = res
                    
    return summary

if __name__ == "__main__":
    import sys
    search_path = sys.argv[1] if len(sys.argv) > 1 else "."
    final_summary = run_scan(search_path)
    
    # Calculate Metrics
    deceptive_count = (final_summary["total_identity_bypass"] + 
                       final_summary["total_boolean_short_circuit"] + 
                       final_summary["total_bypass_keyword"])
    
    percentage = (deceptive_count / final_summary["total_loc"] * 100) if final_summary["total_loc"] > 0 else 0
    
    final_summary["metrics"] = {
        "deceptive_count": deceptive_count,
        "deceptive_percentage": round(percentage, 4),
        "legitimate_ratio": round(final_summary["total_legitimate_constants"] / final_summary["total_loc"] * 100, 4) if final_summary["total_loc"] > 0 else 0
    }
    
    print(json.dumps(final_summary, indent=2))
