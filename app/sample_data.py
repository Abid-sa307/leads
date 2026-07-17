"""
Pre-defined Indian companies and facilities for initial database seeding.
Covers the six requested categories:
1. Industrial Manufacturing Unit
2. Warehouse & Cold Storage
3. Educational Institutes
4. Factories
5. Offices Workplace Management
6. Hospitals Facilities
"""

SECTOR_DATA = {
    "Industrial Manufacturing Unit": [
        {"industry_name": "Tata Steel", "city": "Jamshedpur", "state": "Jharkhand", "country": "IN", "website": "tatasteel.com"},
        {"industry_name": "Reliance Industries", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "ril.com"},
        {"industry_name": "Larsen & Toubro", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "larsentoubro.com"},
        {"industry_name": "Bharat Heavy Electricals Limited", "city": "Bhopal", "state": "Madhya Pradesh", "country": "IN", "website": "bhel.com"},
        {"industry_name": "Hindalco Industries", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "hindalco.com"},
        {"industry_name": "JSW Steel", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "jsw.in"},
        {"industry_name": "Steel Authority of India", "city": "Bhilai", "state": "Chhattisgarh", "country": "IN", "website": "sail.co.in"},
        {"industry_name": "Godrej & Boyce", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "godrej.com"},
        {"industry_name": "Bharat Forge", "city": "Pune", "state": "Maharashtra", "country": "IN", "website": "bharatforge.com"},
        {"industry_name": "Cummins India", "city": "Pune", "state": "Maharashtra", "country": "IN", "website": "cummins.com"},
    ],
    "Warehouse & Cold Storage": [
        {"industry_name": "Snowman Logistics", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "snowman.in"},
        {"industry_name": "Coldman Logistics", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "coldman.in"},
        {"industry_name": "Gubba Cold Storage", "city": "Hyderabad", "state": "Telangana", "country": "IN", "website": "gubbabos.com"},
        {"industry_name": "RK Foodland", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "rkfoodland.com"},
        {"industry_name": "Western Logistics", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "westernlogistics.co.in"},
        {"industry_name": "Mahindra Logistics", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "mahindralogistics.com"},
        {"industry_name": "TCI Cold Chain Solutions", "city": "Gurugram", "state": "Haryana", "country": "IN", "website": "tcilcoldchain.com"},
        {"industry_name": "Kool-ex Warehousing", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "koolex.in"},
        {"industry_name": "Crystal Group", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "crystalgroup.in"},
        {"industry_name": "Gati Kausar", "city": "Gurugram", "state": "Haryana", "country": "IN", "website": "gatikausar.com"},
    ],
    "Educational Institutes": [
        {"industry_name": "Indian Institute of Technology Bombay", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "iitb.ac.in"},
        {"industry_name": "Indian Institute of Technology Delhi", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "iitd.ac.in"},
        {"industry_name": "Indian Institute of Science", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "iisc.ac.in"},
        {"industry_name": "Birla Institute of Technology and Science", "city": "Pilani", "state": "Rajasthan", "country": "IN", "website": "bits-pilani.ac.in"},
        {"industry_name": "Delhi University", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "du.ac.in"},
        {"industry_name": "Indian Institute of Technology Madras", "city": "Chennai", "state": "Tamil Nadu", "country": "IN", "website": "iitm.ac.in"},
        {"industry_name": "Vellore Institute of Technology", "city": "Vellore", "state": "Tamil Nadu", "country": "IN", "website": "vit.ac.in"},
        {"industry_name": "SRM Institute of Science and Technology", "city": "Chennai", "state": "Tamil Nadu", "country": "IN", "website": "srmist.edu.in"},
        {"industry_name": "Manipal Academy of Higher Education", "city": "Manipal", "state": "Karnataka", "country": "IN", "website": "manipal.edu"},
        {"industry_name": "Amity University", "city": "Noida", "state": "Uttar Pradesh", "country": "IN", "website": "amity.edu"},
    ],
    "Factories": [
        {"industry_name": "Maruti Suzuki India", "city": "Gurugram", "state": "Haryana", "country": "IN", "website": "marutisuzuki.com"},
        {"industry_name": "Hero MotoCorp", "city": "Dharuhera", "state": "Haryana", "country": "IN", "website": "heromotocorp.com"},
        {"industry_name": "Asian Paints", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "asianpaints.com"},
        {"industry_name": "UltraTech Cement", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "ultratechcement.com"},
        {"industry_name": "Hindustan Unilever", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "hul.co.in"},
        {"industry_name": "ITC Limited", "city": "Kolkata", "state": "West Bengal", "country": "IN", "website": "itcportal.com"},
        {"industry_name": "Bosch India", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "bosch.in"},
        {"industry_name": "Ambuja Cements", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "ambujacement.com"},
        {"industry_name": "MRF Tyres", "city": "Chennai", "state": "Tamil Nadu", "country": "IN", "website": "mrftyres.com"},
        {"industry_name": "Tata Motors Pune Factory", "city": "Pune", "state": "Maharashtra", "country": "IN", "website": "tatamotors.com"},
    ],
    "Offices Workplace Management": [
        {"industry_name": "WeWork India", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "wework.co.in"},
        {"industry_name": "Smartworks", "city": "Gurugram", "state": "Haryana", "country": "IN", "website": "smartworksoffice.com"},
        {"industry_name": "Awfis Space Solutions", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "awfis.com"},
        {"industry_name": "Innov8 Coworking", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "innov8.work"},
        {"industry_name": "IndiQube", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "indiqube.com"},
        {"industry_name": "Table Space", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "tablespace.in"},
        {"industry_name": "91springboard", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "91springboard.com"},
        {"industry_name": "CoWrks", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "cowrks.com"},
        {"industry_name": "Simpliwork Offices", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "simpliwork.com"},
        {"industry_name": "Regus India", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "regus.com"},
    ],
    "Hospitals Facilities": [
        {"industry_name": "Apollo Hospitals", "city": "Chennai", "state": "Tamil Nadu", "country": "IN", "website": "apollohospitals.com"},
        {"industry_name": "Fortis Healthcare", "city": "Gurugram", "state": "Haryana", "country": "IN", "website": "fortishealthcare.com"},
        {"industry_name": "Max Healthcare", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "maxhealthcare.in"},
        {"industry_name": "Medanta The Medicity", "city": "Gurugram", "state": "Haryana", "country": "IN", "website": "medanta.org"},
        {"industry_name": "Manipal Hospitals", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "manipalhospitals.com"},
        {"industry_name": "Narayana Health", "city": "Bengaluru", "state": "Karnataka", "country": "IN", "website": "narayanahealth.org"},
        {"industry_name": "Kokilaben Dhirubhai Ambani Hospital", "city": "Mumbai", "state": "Maharashtra", "country": "IN", "website": "kokilabenhospital.com"},
        {"industry_name": "Sir Ganga Ram Hospital", "city": "Delhi", "state": "Delhi", "country": "IN", "website": "sgrh.com"},
        {"industry_name": "Aster DM Healthcare", "city": "Kochi", "state": "Kerala", "country": "IN", "website": "asterdmhealthcare.com"},
        {"industry_name": "Christian Medical College Vellore", "city": "Vellore", "state": "Tamil Nadu", "country": "IN", "website": "cmch-vellore.edu"},
    ]
}
