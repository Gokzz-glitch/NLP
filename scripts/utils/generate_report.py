import json, shutil, os, datetime

# Copy fresh log
shutil.copy('logs/batch_audit_results.json', 'audit_evidence/logs/batch_audit_results.json')

# Read results
with open('logs/batch_audit_results.json') as f:
    results = json.load(f)

total = sum(r['hazards'] for r in results)
print('=== MACHA EDGE-SENTINEL: FINAL AUDIT REPORT ===')
print(f'Total Clips Processed : {len(results)}')
print(f'Total Hazards Detected: {total}')
print()
for r in results:
    name = r["clip"].encode('ascii', 'replace').decode('ascii')
    name = (name[:60] + '...') if len(name) > 60 else name
    print(f'  {name:65s} | {r["hazards"]:3d} hazards')

print()
print('Legal RAG Sources (2019 + 2024 CMVR Amendments):')
print('  - MVA 2019  : Sec 183 (Speeding), 184 (Dangerous), 190 (Unsafe), 194D (Helmet)')
print('  - CMVR 2024 : Rule 115 (BS-VI), Indirect Vision Devices, L2-5 Modular Category')
print()

# Save manifest
manifest = {
    'generated_at': datetime.datetime.now().isoformat(),
    'system': 'SmartSalai Edge-Sentinel v2.0',
    'event': 'IIT Madras CoERS 2026 Hackathon',
    'clips_audited': len(results),
    'total_hazards': total,
    'legal_rag_sources': ['MVA_2019', 'CMVR_2024_01', 'CMVR_2024_02', 'CMVR_2024_08'],
    'recordings': os.listdir('audit_evidence/recordings'),
    'logs': os.listdir('audit_evidence/logs'),
    'inference_mode': 'CPU (YOLOv8n local)',
    'backend': 'WebSocket ws://0.0.0.0:8765',
}
with open('audit_evidence/MANIFEST.json', 'w') as f:
    json.dump(manifest, f, indent=2)

print('=== EVIDENCE ARCHIVE ===')
for root, dirs, files in os.walk('audit_evidence'):
    level = root.replace('audit_evidence', '').count(os.sep)
    indent = '  ' * level
    folder = os.path.basename(root)
    print(f'{indent}{folder}/')
    for file in files:
        size = os.path.getsize(os.path.join(root, file))
        print(f'{indent}  {file}  ({size // 1024} KB)')
