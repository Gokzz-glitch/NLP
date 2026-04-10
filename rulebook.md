# Road Safety Hackathon 2026 - Rulebook

## Organization
Organized by COERS, RBG Labs, IIT Madras.

## Problem Domains
1. **DriveLegal**
   - Location-specific traffic laws
   - Fines and automated Challan Calculator
   - Geo-fenced lookup for regulations

2. **RoadWatch**
   - Road quality monitoring
   - Public spending transparency
   - Automated complaint routing

3. **RoadSoS**
   - Location-based emergency services for road accidents
   - Dynamic routing to trauma centers, police, and towing operations

## Technical Constraints & Submission Criteria
- **Global Applicability**: The architecture must easily extend beyond India.
- **Offline Functionality**: Models and logic must be able to deploy locally on devices (e.g., INT8/GGUF models) without constant internet access.
- **Low-Network Robustness**: Critical workflows (like SOS or Legal lookups) must degrade gracefully or operate entirely locally.
- **Open-Source Priority**: Use open/free models and APIs exclusively. (e.g., Llama, Gemma, YOLO, Phi). Proprietary paid endpoints are forbidden in the final evaluation environment.
- **Hardware Profile**: The reference edge device profile has low VRAM. The system must optimize for minimal latency and memory footprints.
