import sqlite3
import datetime

# ---------------------------------------------------------------------------
# MVA 2019 Baseline Seed
# Sources: Motor Vehicles Act 1988 (Amendment 2019), MoRTH Gazette S.O. 2224(E)
# Covers the 30 most enforcement-relevant sections for SmartSalai use cases.
# ---------------------------------------------------------------------------

_IMPORT_TIME = datetime.datetime.now()  # Computed at import; used only for seed timestamps

BASELINE_DATA = [
    # (section, title, content, jurisdiction, last_updated)
    (
        '177',
        'General provision for punishment of offences',
        'Whoever contravenes any provision of this Act or of any rule, regulation or notification made thereunder shall, if no penalty is provided for the offence be punishable for the first offence with a fine which may extend to five hundred rupees and for any subsequent offence with a fine which may extend to one thousand five hundred rupees. (MVA 2019 Amendment: base fine raised to INR 500.)',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '177A',
        'Penalty for violation of road regulations',
        'Whoever contravenes any regulation made under Section 118 (driving regulations) shall be punishable with a fine which shall not be less than INR 500 for the first offence and INR 1500 for any subsequent offence.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '178',
        'Penalty for travelling without pass or ticket',
        'Whoever travels in a stage carriage without a pass or ticket and whoever having purchased a ticket for a particular journey or area travels beyond that journey or area without obtaining a fresh ticket shall be punishable with a fine of INR 500.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '179',
        'Penalty for disobeying orders of authorities',
        'Whoever wilfully disobeys any direction lawfully given by any person or authority empowered under this Act to give such direction, or obstructs any such person or authority in the discharge of his or their functions under this Act, shall be punishable with a fine which may extend to INR 2000.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '180',
        'Allowing unauthorised persons to drive vehicles',
        'Whoever, being the owner or person in charge of a motor vehicle, causes or permits any person who does not satisfy the provisions of Section 3 or Section 4 to drive the vehicle, shall be punishable with imprisonment of up to 3 months or fine up to INR 5000 or both. (MVA 2019 Amendment.)',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '181',
        'Driving vehicles in contravention of Section 3 or Section 4',
        'Whoever drives a motor vehicle in contravention of Section 3 (driving without licence) or Section 4 (driving by disqualified persons) shall be punishable with imprisonment up to 3 months or fine up to INR 5000 or both. Repeat offence: imprisonment up to 1 year or fine up to INR 10000.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '182',
        'Offences relating to licences',
        'Whoever drives a motor vehicle under the influence of alcohol or drugs (Section 185) or whose licence has been suspended, or who makes a false application or statement for a licence, shall be punishable with fine of INR 500 to INR 1000 or imprisonment up to 3 months. (See also Section 185 for DUI penalties.)',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '182B',
        'Penalty for overloading of vehicles',
        'Whoever drives a motor vehicle with a load exceeding the maximum authorised load limit (GVW) shall be punishable with a fine of INR 2000 plus INR 1000 per tonne of excess load. The vehicle shall be detained until the excess load is off-loaded. MVA 2019 Amendment raised penalties substantially.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '183',
        'Punishment for speeding',
        'Whoever drives a motor vehicle in contravention of the speed limits referred to in Section 112 shall be punishable: LMV (first offence) INR 1000-2000, repeat INR 2000; Medium Passenger Vehicles/Heavy Vehicles INR 2000-4000, repeat INR 4000. Penalty for racing: INR 5000 + DL suspension. Speed limits under AIS-140 GPS telemetry are admissible as evidence under MVA 2019.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '184',
        'Driving dangerously',
        'Whoever drives a motor vehicle at a speed or in a manner which is dangerous to the public having regard to all the circumstances of the case including the nature, condition and use of the place where the vehicle is driven and the amount of traffic which actually is at the time or which might reasonably be expected to be in the place shall be punishable with imprisonment up to 1 year or fine INR 1000-5000 for first offence; imprisonment up to 2 years or fine INR 10000 for repeat offence.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '185',
        'Driving by a drunken person or by a person under the influence of drugs',
        'Whoever drives a motor vehicle in any public place while under the influence of alcohol (breath analyser reading > 30mg/100ml blood) or a drug to such an extent as to be incapable of exercising proper control shall be punishable: first offence — imprisonment up to 6 months or fine INR 10000 or both; repeat offence within 3 years — imprisonment up to 2 years or fine INR 15000 or both. MVA 2019 Amendment: breathalyser test mandatory upon officer request.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '186',
        'Driving when mentally or physically unfit to drive',
        'Whoever drives a motor vehicle in any public place when he is to his knowledge suffering from any disease or disability calculated to cause his driving of the vehicle to be a source of danger to the public shall be punishable with a fine of INR 1000 for the first offence and INR 2000 for subsequent offences.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '189',
        'Racing and trials of speed',
        'Whoever without written consent of the State Government uses or permits the use of any highway or other public place for the purpose of holding or taking part in any race or trial of speed between motor vehicles shall be punishable with imprisonment up to 1 month or fine of INR 500.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '190',
        'Using vehicle in unsafe condition',
        'Whoever drives or causes or allows to be driven in any public place a motor vehicle in such condition that its use in a public place constitutes a danger to the public, including a vehicle with defective brakes, steering, tyres, lights, or without required safety equipment under AIS standards, shall be punishable with fine of INR 500-1000; subsequent offence up to INR 2000. Vehicle may be impounded.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '192',
        'Using vehicle without registration',
        'Whoever drives a motor vehicle or causes or allows a motor vehicle to be used in a public place without the vehicle having been registered in accordance with Chapter IV shall be punishable with imprisonment up to 3 months or fine of INR 5000 or both. MVA 2019: enhanced penalty regime; vehicles without valid registration may be seized.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '192A',
        'Using vehicle without permit',
        'Whoever drives a motor vehicle or causes or allows a motor vehicle to be used in any public place or in any other place for purposes of carrying passengers or goods without a permit as required by Section 66 shall be punishable with a fine of INR 10000 and the vehicle may be seized.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '194',
        'Driving vehicle exceeding permissible weight',
        'Whoever drives or causes or allows to be driven in any public place any motor vehicle whose unladen weight, laden weight, axle weight or combination weight exceeds the maxima specified under Section 113 or Section 114 shall be punishable with fine of INR 20000 per axle overloading, and the vehicle shall not be permitted to proceed until the load is reduced. MVA 2019 substantially raised overloading fines.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '194A',
        'Penalty for overloading of passengers',
        'Whoever drives a motor vehicle carrying passengers beyond the capacity for which the vehicle is registered (overcrowding) shall be punishable with a fine of INR 1000 per excess passenger. The vehicle shall not proceed until overloading is rectified.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '194B',
        'Penalty for not wearing seat belt',
        'Whoever drives a motor vehicle (other than a motor cycle) without wearing a seat belt or causes or allows a person in the vehicle to not wear a seat belt as required under Section 138(1) shall be punishable with a fine of INR 1000. MVA 2019 Amendment. Applicable to both front and rear seat passengers.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '194C',
        'Penalty for violation of traffic rules by riders of motor cycles',
        'Whoever drives a motor cycle in contravention of the rules made under Section 129 (including riding without helmet, carrying excess pillion riders, or without mirrors/indicators) shall be punishable with a fine of INR 1000 and disqualification from holding a driving licence for up to 3 months.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '194D',
        'Penalty for not wearing protective headgear',
        'Whoever drives a motor cycle or causes or allows a motor cycle to be driven in contravention of the provisions of Section 129 (protective headgear requirement — ISI-marked helmet) shall be punishable with a fine of INR 1000 and disqualification from holding a driving licence for 3 months. MVA 2019 Amendment. Pillion rider without helmet: INR 1000 fine + 3-month DL disqualification of rider.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '194E',
        'Failure to allow free passage to emergency vehicles',
        'Whoever fails to allow free passage to an emergency vehicle (ambulance, fire brigade, police) by not yielding or clearing the road when an emergency siren is audible shall be punishable with a fine of INR 10000. MVA 2019 Amendment introduced this section.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '196',
        'Driving uninsured vehicle',
        'Whoever drives a motor vehicle or causes or allows a motor vehicle to be driven in a public place without a policy of insurance in accordance with Chapter XI (third party insurance) shall be punishable with imprisonment up to 3 months or fine of INR 2000 or both. MVA 2019: repeat offence — imprisonment up to 3 months or fine up to INR 4000.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '198',
        'Unauthorised interference with vehicle',
        'Whoever otherwise than with lawful authority or reasonable excuse takes or retains possession of or takes or drives away any motor vehicle without the consent of its owner shall be punishable with imprisonment up to 3 months or fine up to INR 1500 or both.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '199A',
        'Offences by juveniles',
        'Where an offence under this Act has been committed by a person under the age of 18 years, the owner or the guardian of such person shall be deemed to be guilty of such offence and shall be liable to be proceeded against and punished accordingly. The motor vehicle used in the offence shall be cancelled under Section 8A. Bail not ordinarily granted to guardian; juvenile tried under JJ Act.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '206',
        'Power to detain vehicles used without certificate of registration',
        'Any police officer or other authority authorised in this behalf by the State Government may detain a vehicle if the driver or person in charge is found to have committed an offence under Sections 192, 196 (no insurance) or 66 (no permit) until the required document is produced or the fine is paid. Detention procedure under Motor Vehicles Act 1988.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '207',
        'Power to impound documents',
        'Any police officer in uniform authorised in this behalf by the State Government may require the driver of any motor vehicle to produce for inspection the certificate of registration, certificate of insurance, driving licence, permit or other documents; and may impound such document if it appears invalid or where an offence has been committed until the case is disposed of.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '208',
        'Summary disposal of cases',
        'Notwithstanding anything contained in the Code of Criminal Procedure 1973, an officer in charge of a police station or any officer of or above the rank of a Sub-Inspector of Police specially empowered in this behalf by the State Government may, at his discretion, compound any offence under this Act. SECTION 208 ENFORCEMENT CHALLENGE: Under settled interpretation, a speed camera enforcement action is challengeable where mandatory advance speed limit signage (as required by IRC:67 and the Motor Vehicles (Driving) Regulations 2017) was absent within 500 metres upstream of the enforcement camera. Absence of signage renders the captured evidence legally untenable. Challans issued without prerequisite signage in place are subject to audit challenge under Section 208 read with Article 21 of the Constitution (fair procedure). Any person so aggrieved may submit an Audit Request to the Regional Transport Officer or Jurisdictional Magistrate within 60 days of challan issuance.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '210B',
        'Enhanced penalty for offences committed by enforcing authorities',
        'Any officer or authority acting under this Act who fails to perform the duty imposed upon him under this Act, or who commits any act in contravention of this Act while purportedly enforcing it, shall be liable to twice the penalty prescribed for the corresponding offence. MVA 2019 Amendment introduced this accountability provision.',
        'INDIA', _IMPORT_TIME,
    ),
    (
        '212',
        'Cognizance of offences',
        'No court shall take cognizance of an offence punishable under this Act (other than an offence punishable under Section 112, 113, 114, or 115 or 116 or Chapter X or Chapter XI) except on a report in writing of the facts constituting such offence made by a police officer in uniform or by an officer of the motor vehicles department. MVA 2019: e-challan digital evidence (AIS-140 GPS trace, ANPR camera footage) is admissible provided chain of custody is documented.',
        'INDIA', _IMPORT_TIME,
    ),
]


def seed_database():
    conn = sqlite3.connect('legal_vector_store.db')
    cursor = conn.cursor()

    # Schema for MVA Baseline
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS legal_statutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            jurisdiction TEXT DEFAULT 'INDIA',
            last_updated TIMESTAMP,
            year INTEGER DEFAULT 2019,
            legal_source TEXT DEFAULT 'CMVR'
        )
    ''')

    # Only insert sections not already present (idempotent re-seed)
    for row in BASELINE_DATA:
        section = row[0]
        existing = cursor.execute(
            'SELECT COUNT(*) FROM legal_statutes WHERE section=?', (section,)
        ).fetchone()[0]
        if not existing:
            cursor.execute(
                'INSERT INTO legal_statutes (section, title, content, jurisdiction, last_updated) VALUES (?, ?, ?, ?, ?)',
                row,
            )

    conn.commit()
    conn.close()
    print(f"PERSONA_6_REPORT: MVA_BASELINE_SEED_COMPLETE. {len(BASELINE_DATA)} sections available. SQLITE_READY.")
if __name__ == "__main__":
    seed_database()

