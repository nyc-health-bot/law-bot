"""Shared utilities for NYC Health Code PDF scraping."""

import io
import urllib.request

import pypdf

BASE = "https://www.nyc.gov"
LANDING_URL = "https://www.nyc.gov/site/doh/about/about-doh/health-code-and-rules.page"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# (number, title, path)  — path relative to BASE
ARTICLES = [
    ("1",    "Short Title and General Definitions",                            "/assets/doh/downloads/pdf/about/healthcode/health-code-article1.pdf"),
    ("3",    "General Provisions",                                             "/assets/doh/downloads/pdf/about/healthcode/health-code-article3.pdf"),
    ("5",    "Permits",                                                        "/assets/doh/downloads/pdf/about/healthcode/health-code-article5.pdf"),
    ("9",    "Petitioning Board to Commence Rulemaking",                       "/assets/doh/downloads/pdf/about/healthcode/health-code-article9.pdf"),
    ("11",   "Reportable Diseases and Conditions",                             "/assets/doh/downloads/pdf/about/healthcode/health-code-article11.pdf"),
    ("13",   "Laboratories",                                                   "/assets/doh/downloads/pdf/about/healthcode/health-code-article13.pdf"),
    ("15",   "Handling Live Pathogenic Organisms",                             "/assets/doh/downloads/pdf/about/healthcode/health-code-article15.pdf"),
    ("43",   "School Based Programs for Children Ages 3 Through 5",            "/assets/doh/downloads/pdf/about/healthcode/health-code-article43.pdf"),
    ("45",   "Schools and Children's Institutions",                            "/assets/doh/downloads/pdf/about/healthcode/health-code-article45.pdf"),
    ("47",   "Child Care Programs and Family Shelter-Based Drop-off Child Supervision Programs", "/assets/doh/downloads/pdf/about/healthcode/health-code-article47.pdf"),
    ("48",   "Day Camps, Overnight Camps, and Traveling Day Camps",            "/assets/doh/downloads/pdf/about/healthcode/health-code-article48.pdf"),
    ("48-a", "Year-Round After-School and Youth Programs",                     "/assets/doh/downloads/pdf/about/healthcode/health-code-article48-a.pdf"),
    ("49",   "Schools",                                                        "/assets/doh/downloads/pdf/about/healthcode/health-code-article49.pdf"),
    ("51",   "Children's Institutions",                                        "/assets/doh/downloads/pdf/about/healthcode/health-code-article51.pdf"),
    ("71",   "Food, Drugs and Cosmetics",                                      "/assets/doh/downloads/pdf/about/healthcode/health-code-article71.pdf"),
    ("81",   "Food Preparation and Food Establishments",                       "/assets/doh/downloads/pdf/about/healthcode/health-code-article81.pdf"),
    ("88",   "Temporary Food Establishments",                                  "/assets/doh/downloads/pdf/about/healthcode/health-code-article88.pdf"),
    ("89",   "Mobile Food Vending",                                            "/assets/doh/downloads/pdf/about/healthcode/health-code-article89.pdf"),
    ("115",  "Formula Preparation",                                            "/assets/doh/downloads/pdf/about/healthcode/health-code-article115.pdf"),
    ("121",  "Other Food Establishments",                                      "/assets/doh/downloads/pdf/about/healthcode/health-code-article121.pdf"),
    ("131",  "Buildings Generally",                                            "/assets/doh/downloads/pdf/about/healthcode/health-code-article131.pdf"),
    ("139",  "Public Transportation Facilities",                               "/assets/doh/downloads/pdf/about/healthcode/health-code-article139.pdf"),
    ("141",  "Water Supply Safety Standards",                                  "/assets/doh/downloads/pdf/about/healthcode/health-code-article141.pdf"),
    ("143",  "Disposal of Sewage",                                             "/assets/doh/downloads/pdf/about/healthcode/health-code-article143.pdf"),
    ("151",  "Rodents, Insects, Other Pests",                                  "/assets/doh/downloads/pdf/about/healthcode/health-code-article151.pdf"),
    ("161",  "Animals",                                                        "/assets/doh/downloads/pdf/about/healthcode/health-code-article161.pdf"),
    ("163",  "Barber Shops",                                                   "/assets/doh/downloads/pdf/about/healthcode/health-code-article163.pdf"),
    ("165",  "Bathing Establishments",                                         "/assets/doh/downloads/pdf/about/healthcode/health-code-article165.pdf"),
    ("167",  "Bathing Beaches",                                                "/assets/doh/downloads/pdf/about/healthcode/health-code-article167.pdf"),
    ("173",  "Hazardous Substances",                                           "/assets/doh/downloads/pdf/about/healthcode/health-code-article173.pdf"),
    ("175",  "Radiation Control",                                              "/assets/doh/downloads/pdf/about/healthcode/health-code-article175.pdf"),
    ("177",  "Tanning Facilities",                                             "/assets/doh/downloads/pdf/about/healthcode/health-code-article177.pdf"),
    ("181",  "Protection of Public Health Generally",                          "/assets/doh/downloads/pdf/about/healthcode/health-code-article181.pdf"),
    ("201",  "Births",                                                         "/assets/doh/downloads/pdf/about/healthcode/health-code-article201.pdf"),
    ("203",  "Termination of Pregnancy",                                       "/assets/doh/downloads/pdf/about/healthcode/health-code-article203.pdf"),
    ("205",  "Deaths and Disposal of Human Remains",                           "/assets/doh/downloads/pdf/about/healthcode/health-code-article205.pdf"),
    ("207",  "General Vital Statistics Provisions",                            "/assets/doh/downloads/pdf/about/healthcode/health-code-article207.pdf"),
]

# Commissioner's Regulations
CHAPTERS = [
    ("1",  "Required Signs",                                                        "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter1.pdf"),
    ("3",  "Performance Summary Cards and Penalties for Child Care Programs",       "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter3.pdf"),
    ("4",  "Health, Safety and Well-Being of Rental Horses",                        "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter4.pdf"),
    ("5",  "Pet Shops",                                                             "/assets/doh/downloads/pdf/about/healthcode/chapter5-petshops.pdf"),
    ("6",  "Mobile Food Vending",                                                   "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter6.pdf"),
    ("7",  "Adjudicatory Hearings and Violation Fines and Penalties",               "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter7.pdf"),
    ("8",  "Cooling Towers",                                                        "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter8.pdf"),
    ("9",  "Raw Salt-Cured Air-Dried Fish",                                         "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter9.pdf"),
    ("10", "Smoking and the Use of Electronic Cigarettes Under the NYC Smoke-Free Air Act", "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter10.pdf"),
    ("12", "Window Falls Prevention",                                               "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter12.pdf"),
    ("13", "Cigarette and Tobacco Product Sales",                                   "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter13.pdf"),
    ("14", "Cleaning Park Playground Equipment",                                    "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter14.pdf"),
    ("16", "Criteria for Issuing Special Vehicle Identification Permits to Disabled Persons", "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter16.pdf"),
    ("17", "Tripartite General Orders",                                             "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter17.pdf"),
    ("18", "Resuscitation Equipment in Public Places",                              "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter18.pdf"),
    ("19", "Waiting List Rules for Temporary Mobile Food Unit Permits",             "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter19.pdf"),
    ("21", "Health Academy Courses and Department Fees",                            "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter21.pdf"),
    ("22", "Tattooists and Applying Tattoos",                                       "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter22.pdf"),
    ("23", "Food Service Establishment Sanitary Inspection Procedure",              "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter23.pdf"),
    ("24", "Automated External Defibrillators in Certain Public Places",            "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter24.pdf"),
    ("25", "Service of Final Orders in Assisted Outpatient Treatment",              "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter25.pdf"),
    ("26", "Establishment and Maintenance of Separate Borough Specific Waiting Lists for Fresh Fruit and Vegetable Vendors", "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter26.pdf"),
    ("27", "Food Allergy Information",                                              "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter27.pdf"),
    ("28", "Restriction on the Sale of Certain Flavored Tobacco Products and Electronic Cigarettes", "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter28.pdf"),
    ("29", "Animal Population Control Program",                                     "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter29.pdf"),
    ("30", "Volatile Organic Compounds in Carpet and Carpet Cushion",               "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter30.pdf"),
    ("31", "Drinking Water Tank Inspections",                                       "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter31.pdf"),
    ("32", "Dogs in Outdoor Dining Areas",                                          "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter32.pdf"),
    ("33", "Operation of Body Scanners in Correctional Facilities",                 "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter33.pdf"),
    ("34", "Grocery Delivery Program",                                              "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter34.pdf"),
    ("35", "Designating Rat Mitigation Zones",                                      "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter35.pdf"),
    ("36", "Needle, Syringe and Sharps Buyback Pilot Program",                      "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter36.pdf"),
    ("37", "Petitioning the Department to Commence Rulemaking",                     "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter37.pdf"),
    ("38", "Program to Cancel Medical Debt",                                        "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter38.pdf"),
    ("39", "Added Sugar Warning",                                                   "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter39.pdf"),
    ("40", "Certification of Radon and Other Vapors Levels in Certain Basement and Cellar Apartments", "/assets/doh/downloads/pdf/about/healthcode/health-code-chapter40.pdf"),
]


def fetch_pdf(path: str) -> bytes:
    url = BASE + path if path.startswith("/") else path
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def extract_pdf_text(pdf_bytes: bytes) -> dict:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append({"page": i + 1, "text": text})
    return {
        "page_count": len(reader.pages),
        "pages": pages,
        "text": "\n\n".join(p["text"] for p in pages),
    }


def parse_sections(text: str) -> list:
    """Split extracted PDF text into individual sections on § markers.

    Handles all formatting variants found across NYC Health Code PDFs:
      §167.01  Title          (article format, 2 spaces)
      §32-01 Title            (chapter format, 1 space)
      §33-01. Title           (chapter format, trailing period after number)
      §48-A.01  Title         (article 48-a, uppercase letter in number)
    TOC entries are excluded because their bodies are empty (next § follows immediately).
    """
    import re

    # Some PDFs (e.g. chapter 10) split "§10\n-01" across a line break — rejoin before parsing
    text = re.sub(r'(§\s*\d+)\n(-\d+)', r'\1\2', text)

    # Section number variants:
    #   \d+(?:-[A-Za-z])?  — base with optional letter subpart (e.g. 48-A)
    #   [-.]               — separator (dot or dash)
    #   \d+[A-Za-z]?       — section digits with optional trailing letter
    #   \.?                — optional trailing period before title (e.g. §33-01. Title)
    pattern = re.compile(
        r'^\s*§\s*(\d+(?:-[A-Za-z])?[-.]\d+[A-Za-z]?)\.?\s+([^\n]+)',
        re.MULTILINE,
    )

    matches = list(pattern.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        number = m.group(1).strip()
        title = m.group(2).strip().rstrip(".")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        # Title ending with ; or , means it wrapped to the next line — absorb that line
        if title.endswith((";", ",")):
            lines = body.splitlines()
            if lines:
                first = lines[0].strip()
                if first and not re.match(r'^[\(\d]', first):
                    title = title + " " + first.rstrip(".")
                    body = "\n".join(lines[1:]).strip()

        if body:
            sections.append({"section": number, "title": title, "text": body})

    # Deduplicate: TOC entries slip through when their title wraps; keep the longest body
    seen = {}
    for s in sections:
        k = s["section"]
        if k not in seen or len(s["text"]) > len(seen[k]["text"]):
            seen[k] = s

    def _section_sort_key(sec):
        nums = re.findall(r'\d+', sec["section"])
        letters = re.findall(r'[A-Za-z]', sec["section"])
        return (int(nums[0]) if nums else 0, letters[0].lower() if letters else "", int(nums[-1]) if len(nums) > 1 else 0)

    return sorted(seen.values(), key=_section_sort_key)


def article_filename(number: str) -> str:
    slug = number.replace("-", "")
    digits = "".join(c for c in slug if c.isdigit())
    suffix = "".join(c for c in slug if not c.isdigit())
    return f"article_{int(digits):03d}{suffix}.json"


def chapter_filename(number: str) -> str:
    return f"chapter_{int(number):02d}.json"
