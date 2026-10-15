"""Curriculum plans used by the Academic department's Curriculum page (BSIT, BSCS, B.S. Engineering, B.Eng., BS Entrep).

Years 1-3 and the Summer term are transcribed from the supplied BSIT curriculum
(Revised June 2018, per CMO no. 25 s. 2015, compliant with CMO no. 57 s. 2017).
Fourth Year was NOT in the supplied pages, so it is a DRAFT (``draft=True``) that
the department must confirm or replace. This file only supplies the STARTING data: on first
run it is copied into the database, and from then on an Admin (or staff granted Curriculum
access under Staff Accounts > Advanced module access control) edits the curriculum from the
Curriculum page. Unit totals are always calculated, never typed in.
"""

NONE = "NONE"
CAPSTONE_PREREQ = "All subjects from first year to second year second sem were taken and no failure, INC or 4.0"

# (course no., descriptive title, units, pre-requisite)
CURRICULUM_BSIT = [
    {"year": 1, "term": "First Semester", "courses": [
        ("FIL 111", "Kontekstwalisadong Komunikasyon sa Filipino (KOMFIL)", 3, NONE),
        ("GE 101", "Understanding the Self", 3, NONE),
        ("GE 102", "Readings in Philippine History", 3, NONE),
        ("NSTP 101", "National Service Training Program 1", 3, NONE),
        ("PE 101", "Movement Enhancement", 2, NONE),
        ("IT 101", "Information Technology Fundamentals with Software Applications", 2, NONE),
        ("IT 101 L", "Information Technology Fundamentals with Software Applications (Laboratory)", 1, NONE),
        ("IT 102", "Accounting Principle", 3, NONE),
        ("IT 103", "Computer Programming I Java", 2, NONE),
        ("IT 103 L", "Computer Programming I - Java (Laboratory)", 1, NONE),
        ("IT 104", "Discrete Mathematics", 3, NONE),
    ]},
    {"year": 1, "term": "Second Semester", "courses": [
        ("GE 103", "The Contemporary World", 3, NONE),
        ("GE 104", "Mathematics in the Modern World", 3, NONE),
        ("GE 105", "Purposive Communication", 3, NONE),
        ("NSTP 102", "National Service Training Program 2", 3, "NSTP 101"),
        ("PE 102", "Fitness Exercises", 2, NONE),
        ("IT 105", "Mobile Development", 2, "IT 103"),
        ("IT 105 L", "Mobile Development (Laboratory)", 1, "IT 103 L"),
        ("IT 106", "Introduction to Computing Computer Organization", 3, NONE),
        ("IT 107", "Multimedia Systems", 2, NONE),
        ("IT 107 L", "Multimedia Systems (Laboratory)", 1, NONE),
        ("IT 108", "Programming II - Java", 2, "IT 103"),
        ("IT 108 L", "Programming II - Java (Laboratory)", 1, "IT 103 L"),
    ]},
    {"year": 2, "term": "First Semester", "courses": [
        ("GE 109", "Readings in Rizal's Life and Works", 3, NONE),
        ("GE 113", "Living in the IT Era", 3, NONE),
        ("PE 103", "Physical Activities towards Health & Fitness I", 2, NONE),
        ("IT 109", "IT Elective I - Platform Technologies", 2, "IT 108"),
        ("IT 109 L", "IT Elective I - Platform Technologies (Laboratory)", 1, "IT 108 L"),
        ("IT 110", "Data Structure and Algorithms", 3, "IT 108"),
        ("IT 111", "Fundamentals of Database Systems", 2, "IT 107"),
        ("IT 111 L", "Fundamentals of Database Systems (Laboratory)", 1, "IT 107 L"),
        ("IT 112", "Integrative Programming and Technologies I", 2, "IT 107"),
        ("IT 112 L", "Integrative Programming and Technologies I (Laboratory)", 1, "IT 107 L"),
        ("IT 113", "CISCO I - Network Fundamentals", 2, NONE),
        ("IT 113 L", "CISCO I - Network Fundamentals (Laboratory)", 1, NONE),
    ]},
    {"year": 2, "term": "Second Semester", "courses": [
        ("FIL 114", "Sosyedad at Literatura", 3, "FIL 111"),
        ("GE 107", "Science, Technology & Society", 3, NONE),
        ("GE 106", "Art Appreciation", 3, NONE),
        ("PE 104", "Physical Activities towards Health & Fitness II", 2, NONE),
        ("IT 114", "IT Elective II - Object Oriented Programming", 2, "IT 108"),
        ("IT 114 L", "IT Elective II - Object Oriented Programming (Laboratory)", 1, "IT 108 L"),
        ("IT 115", "Introduction to Human Computer Interaction", 3, "IT 107, IT 104"),
        ("IT 116", "CISCO II - Routing and Switching Essentials", 2, "IT 113"),
        ("IT 116 L", "CISCO II - Routing and Switching Essentials (Laboratory)", 1, "IT 113 L"),
        ("IT 117", "Systems Integration and Architecture I", 2, "IT 112"),
        ("IT 117 L", "Systems Integration and Architecture I (Laboratory)", 1, "IT 112 L"),
    ]},
    {"year": 3, "term": "First Semester", "courses": [
        ("FIL 115", "Senesosyedad/Pelikulang Panlipunan", 3, "FIL 114"),
        ("GE 117", "The Entrepreneurial Mind", 3, NONE),
        ("IT 118", "IT Elective III - Integrative Programming Technologies II", 2, "IT 117"),
        ("IT 118 L", "IT Elective III - Integrative Programming Technologies II (Laboratory)", 1, "IT 117 L"),
        ("IT 119", "IT Elective IV - Web Systems and Technologies", 2, "IT 117"),
        ("IT 119 L", "IT Elective IV - Web Systems and Technologies (Laboratory)", 1, "IT 117 L"),
        ("IT 120", "Geographic Information Systems", 2, NONE),
        ("IT 120 L", "Geographic Information Systems (Laboratory)", 1, NONE),
        ("IT 121", "Information Management I", 2, "IT 108"),
        ("IT 121 L", "Information Management I (Laboratory)", 1, "IT 108 L"),
        ("IT 122", "Systems Analysis and Design", 2, NONE),
        ("IT 122 L", "Systems Analysis and Design (Laboratory)", 1, NONE),
    ]},
    {"year": 3, "term": "Second Semester", "courses": [
        ("GE 108", "Ethics", 3, NONE),
        ("IT 123", "IT Elective V - System Integration & Architecture II", 2, "IT 117"),
        ("IT 123 L", "IT Elective V - System Integration & Architecture II (Laboratory)", 1, "IT 117"),
        ("IT 124", "Quantitative Methods with Simulations and Modeling", 2, "IT 107"),
        ("IT 124 L", "Quantitative Methods with Simulations and Modeling (Laboratory)", 1, "IT 107 L"),
        ("IT 125", "Information Assurance & Security I", 2, "IT 117"),
        ("IT 125 L", "Information Assurance & Security I (Laboratory)", 1, "IT 117 L"),
        ("IT 126", "Social and Professional Issues", 3, NONE),
        ("IT 127", "Application Development and Emerging Technologies", 2, "IT 111"),
        ("IT 127 L", "Application Development and Emerging Technologies (Laboratory)", 1, "IT 111 L"),
        ("IT 128", "Capstone Project I", 2, CAPSTONE_PREREQ),
        ("IT 128 L", "Capstone Project I (Laboratory)", 1, CAPSTONE_PREREQ),
    ]},
    {"year": 3, "term": "Summer", "courses": [
        ("GE 119", "Philippine Popular Culture", 3, NONE),
        ("IT 129", "System Administration and Maintenance", 2, "IT 107"),
        ("IT 129 L", "System Administration and Maintenance (Laboratory)", 1, "IT 107 L"),
    ]},
    # DRAFT: not part of the supplied pages. Confirm or replace with the official Fourth Year.
    {"year": 4, "term": "First Semester", "draft": True, "courses": [
        ("IT 130", "Capstone Project II", 2, "IT 128"),
        ("IT 130 L", "Capstone Project II (Laboratory)", 1, "IT 128 L"),
        ("IT 131", "Information Assurance & Security II", 2, "IT 125"),
        ("IT 131 L", "Information Assurance & Security II (Laboratory)", 1, "IT 125 L"),
    ]},
    {"year": 4, "term": "Second Semester", "draft": True, "courses": [
        ("IT 132", "Practicum / On-the-Job Training", 6, "IT 130, IT 130 L"),
    ]},
]

YEAR_LABELS = {1: "First Year", 2: "Second Year", 3: "Third Year", 4: "Fourth Year"}
CURRICULUM = CURRICULUM_BSIT  # backwards-compatible name


# ---------------------------------------------------------------------------------------------
# SUGGESTED plans (draft=True). These follow the CHED framework for each program but are NOT
# an official curriculum of the school. Confirm or replace every row before using for enrollment.
# ---------------------------------------------------------------------------------------------
def _t(year, term, courses, draft=True):
    return {"year": year, "term": term, "draft": draft, "courses": courses}

# GE codes used by the suggested plans (CMO 20 s. 2013 core + CMO 4 s. 2018 Filipino)
_GE = {
    101: "Understanding the Self", 102: "Readings in Philippine History", 103: "Mathematics in the Modern World",
    104: "The Contemporary World", 105: "Purposive Communication", 106: "Art Appreciation",
    107: "Science, Technology & Society", 108: "Ethics", 109: "Readings in Rizal's Life and Works",
}
def _ge(n, prereq=NONE): return (f"GE {n}", _GE[n], 3, prereq)
def _pe(n): return (f"PE {100 + n}", ["Movement Competency Training", "Exercise-based Fitness Activities",
                                      "Physical Activities towards Health & Fitness I",
                                      "Physical Activities towards Health & Fitness II"][n - 1], 2, NONE if n == 1 else f"PE {99 + n}")
def _nstp(n): return (f"NSTP {100 + n}", f"National Service Training Program {n}", 3, NONE if n == 1 else "NSTP 101")
FIL1 = ("FIL 101", "Kontekstwalisadong Komunikasyon sa Filipino", 3, NONE)
FIL2 = ("FIL 102", "Sosyedad at Literatura", 3, "FIL 101")

# ---- BS Computer Science (CHED CMO No. 25, s. 2015; GE per CMO 20 s. 2013 and CMO 4 s. 2018) ----
CURRICULUM_BSCS = [
    _t(1, "First Semester", [_ge(101), _ge(103), _ge(105), FIL1,
        ("CC 101", "Introduction to Computing", 3, NONE), ("CC 102", "Fundamentals of Programming", 3, NONE),
        ("MATH 101", "Calculus 1 (Differential Calculus)", 3, NONE), _pe(1), _nstp(1)]),
    _t(1, "Second Semester", [_ge(102), _ge(104), FIL2,
        ("CC 103", "Intermediate Programming", 3, "CC 102"), ("CS 101", "Discrete Structures 1", 3, NONE),
        ("MATH 102", "Calculus 2 (Integral Calculus)", 3, "MATH 101"), _pe(2), _nstp(2)]),
    _t(2, "First Semester", [_ge(106), _ge(107),
        ("CS 201", "Data Structures and Algorithms", 3, "CC 103"), ("CS 202", "Discrete Structures 2", 3, "CS 101"),
        ("CS 203", "Computer Organization with Assembly Language", 3, "CC 103"),
        ("CS 204", "Linear Algebra", 3, "MATH 101"), ("CS 205", "Information Management", 3, "CC 103"), _pe(3)]),
    _t(2, "Second Semester", [_ge(108), ("GE 110", "Living in the IT Era (GE Elective 1)", 3, NONE),
        ("CS 206", "Algorithms and Complexity", 3, "CS 201, CS 202"), ("CS 207", "Operating Systems", 3, "CS 201, CS 203"),
        ("CS 208", "Programming Languages", 3, "CS 201"), ("CS 209", "Networks and Communications", 3, "CS 203"),
        ("CS 210", "Probability and Statistics", 3, "MATH 102"), _pe(4)]),
    _t(3, "First Semester", [_ge(109),
        ("CS 301", "Software Engineering 1", 3, "CS 205"), ("CS 302", "Automata Theory and Formal Languages", 3, "CS 206"),
        ("CS 303", "Human Computer Interaction", 3, "CS 201"), ("CS 304", "Information Assurance and Security", 3, "CS 209"),
        ("CS 305", "Intelligent Systems", 3, "CS 206"), ("CS 306", "Parallel and Distributed Computing", 3, "CS 207"),
        ("CS 307", "CS Elective 1", 3, "CS 206")]),
    _t(3, "Second Semester", [("GE 111", "The Entrepreneurial Mind (GE Elective 2)", 3, NONE),
        ("CS 308", "Software Engineering 2", 3, "CS 301"), ("CS 309", "Graphics and Visual Computing", 3, "CS 206"),
        ("CS 310", "Social Issues and Professional Practice", 3, NONE), ("CS 311", "Computational Science", 3, "CS 210, CS 206"),
        ("CS 312", "Methods of Research", 3, "CS 301"), ("CS 313", "CS Elective 2", 3, "CS 206")]),
    _t(3, "Summer", [("GE 112", "Philippine Popular Culture (GE Elective 3)", 3, NONE),
        ("CS 314", "CS Practicum (minimum 162 hours)", 3, "Regular 3rd Year standing")]),
    _t(4, "First Semester", [("CS 401", "Thesis Writing 1", 3, "CS 312"), ("CS 402", "Platform-based Development", 3, "CS 308"),
        ("CS 403", "Fundamentals of Data Science", 3, "CS 210"), ("CS 404", "CS Elective 3", 3, "CS 206")]),
    _t(4, "Second Semester", [("CS 405", "Thesis Writing 2", 3, "CS 401"), ("CS 406", "Software Testing and Quality Assurance", 3, "CS 308"),
        ("CS 407", "CS Elective 4", 3, "CS 206"), ("CS 408", "Seminar on Emerging Technologies", 3, "CS 401")]),
]

# ---- BS Entrepreneurship (CHED CMO No. 18, s. 2017; GE per CMO 20 s. 2013 and CMO 4 s. 2018) ----
CURRICULUM_BSENTREP = [
    _t(1, "First Semester", [_ge(101), _ge(102), FIL1, ("ECON 101", "Basic Microeconomics", 3, NONE),
        ("ACC 101", "Fundamentals of Accounting", 3, NONE), ("MGT 101", "Human Resource Management", 3, NONE), _pe(1), _nstp(1)]),
    _t(1, "Second Semester", [_ge(103), _ge(105), FIL2, ("ENT 101", "Entrepreneurial Behavior", 3, NONE),
        ("MKT 101", "Marketing Management", 3, NONE), ("ACC 102", "Managerial Accounting", 3, "ACC 101"), _pe(2), _nstp(2)]),
    _t(2, "First Semester", [_ge(106), _ge(107), _ge(108), ("ENT 201", "Opportunity Seeking", 3, "ENT 101"),
        ("ENT 202", "Innovation Management", 3, "ENT 101"), ("FIN 201", "Financial Management", 3, "ACC 102"),
        ("OPS 201", "Operations Management", 3, NONE), _pe(3)]),
    _t(2, "Second Semester", [_ge(109), ("GE 110", "Living in the IT Era (GE Elective 1)", 3, NONE),
        ("ENT 203", "Social Entrepreneurship", 3, "ENT 101"), ("ENT 204", "Entrepreneurial Marketing", 3, "MKT 101"),
        ("BLAW 201", "Business Law and Taxation", 3, NONE), ("STAT 201", "Business Statistics", 3, NONE),
        ("ENT 205", "Entrepreneurship Elective 1", 3, "ENT 201"), _pe(4)]),
    _t(3, "First Semester", [("GE 111", "Philippine Popular Culture (GE Elective 2)", 3, NONE),
        ("ENT 301", "Entrepreneurial Management", 3, "ENT 202, FIN 201"), ("ENT 302", "Business Plan Preparation", 3, "ENT 201, ENT 204"),
        ("ENT 303", "Supply Chain and Logistics Management", 3, "OPS 201"), ("ENT 304", "Business Research Methods", 3, "STAT 201"),
        ("ENT 305", "Entrepreneurial Finance", 3, "FIN 201"), ("ENT 306", "Entrepreneurship Elective 2", 3, "ENT 201")]),
    _t(3, "Second Semester", [("ENT 307", "Business Plan Defense and Financing", 3, "ENT 302"),
        ("ENT 308", "Technology Entrepreneurship", 3, "ENT 301"), ("ENT 309", "Entrepreneurial Leadership in an Organization", 3, "ENT 301"),
        ("ENT 310", "Digital Marketing and E-Commerce", 3, "ENT 204"), ("ENT 311", "Business Ethics and Social Responsibility", 3, NONE),
        ("ENT 312", "Entrepreneurship Elective 3", 3, "ENT 201")]),
    _t(3, "Summer", [("ENT 313", "Entrepreneurship Practicum (minimum 300 hours)", 6, "Completed Third Year courses")]),
    _t(4, "First Semester", [("ENT 401", "Business Plan Implementation 1", 3, "ENT 307"), ("ENT 402", "Strategic Management", 3, "ENT 301"),
        ("ENT 403", "Family Business and Small Enterprise Management", 3, "ENT 301"), ("ENT 404", "Entrepreneurship Elective 4", 3, "ENT 201")]),
    _t(4, "Second Semester", [("ENT 405", "Business Plan Implementation 2", 3, "ENT 401"), ("ENT 406", "Entrepreneurship Seminar", 3, "ENT 401"),
        ("ENT 407", "Global Entrepreneurship and Trade", 3, "ENT 301")]),
]

# ---- Engineering plans: unit counts follow the usual lecture (3) + laboratory (1) pairing ----
# Engineering does not take Mathematics in the Modern World or the Filipino GE courses (Calculus and
# the engineering sciences replace them), so those are left out of both plans below.
def _lab(code, title, prereq=NONE, units=1):
    return (f"{code} L", f"{title} (Laboratory)", units, prereq)

# ---- B.S. in Engineering: broad engineering foundation (math, science, basic engineering sciences) ----
CURRICULUM_BSENG = [
    _t(1, "First Semester", [_ge(101), _ge(105),
        ("MATH 101", "Calculus 1 (Differential Calculus)", 3, NONE),
        ("CHEM 101", "Chemistry for Engineers", 3, NONE), _lab("CHEM 101", "Chemistry for Engineers"),
        ("ENGG 101", "Engineering Orientation and Ethics", 1, NONE),
        ("ENGG 102", "Engineering Drawing and Plans", 1, NONE),
        ("ENGG 103", "Computer Fundamentals and Programming for Engineers", 2, NONE), _lab("ENGG 103", "Computer Fundamentals and Programming for Engineers"),
        _pe(1), _nstp(1)]),
    _t(1, "Second Semester", [_ge(102), _ge(104),
        ("MATH 102", "Calculus 2 (Integral Calculus)", 3, "MATH 101"),
        ("PHYS 101", "Physics for Engineers (Mechanics)", 3, "MATH 101"), _lab("PHYS 101", "Physics for Engineers (Mechanics)", "MATH 101"),
        ("ENGG 104", "Engineering Mechanics: Statics of Rigid Bodies", 3, "MATH 101"),
        ("ENGG 105", "Computer-Aided Drafting", 1, "ENGG 102"), _lab("ENGG 105", "Computer-Aided Drafting", "ENGG 102"),
        _pe(2), _nstp(2)]),
    _t(2, "First Semester", [_ge(106),
        ("MATH 201", "Differential Equations", 3, "MATH 102"),
        ("MATH 202", "Engineering Data Analysis (Probability and Statistics)", 3, "MATH 102"),
        ("PHYS 201", "Physics for Engineers (Electricity, Magnetism and Optics)", 3, "PHYS 101"), _lab("PHYS 201", "Physics for Engineers (Electricity, Magnetism and Optics)", "PHYS 101"),
        ("ENGG 201", "Engineering Mechanics: Dynamics of Rigid Bodies", 3, "ENGG 104, MATH 102"),
        ("ENGG 202", "Mechanics of Deformable Bodies", 3, "ENGG 104"),
        _pe(3)]),
    _t(2, "Second Semester", [_ge(107),
        ("MATH 203", "Numerical Methods and Analysis", 3, "MATH 201, ENGG 103"),
        ("ENGG 203", "Engineering Economy", 3, "MATH 102"),
        ("ENGG 204", "Thermodynamics", 3, "PHYS 101, MATH 102"),
        ("ENGG 205", "Basic Electrical and Electronics Engineering", 3, "PHYS 201"), _lab("ENGG 205", "Basic Electrical and Electronics Engineering", "PHYS 201"),
        ("ENGG 206", "Engineering Materials", 3, "CHEM 101, ENGG 202"), _lab("ENGG 206", "Engineering Materials", "CHEM 101 L"),
        _pe(4)]),
    _t(3, "First Semester", [_ge(108),
        ("ENGG 301", "Fluid Mechanics", 3, "ENGG 201"), _lab("ENGG 301", "Fluid Mechanics", "ENGG 201"),
        ("ENGG 302", "Engineering Management and Project Planning", 3, "ENGG 203"),
        ("ENGG 303", "Safety, Health and Environmental Engineering", 3, NONE),
        ("ENGG 304", "Research Methods for Engineers", 3, "MATH 202"),
        ("ENGG 305", "Engineering Elective 1", 3, "ENGG 202")]),
    _t(3, "Second Semester", [_ge(109),
        ("ENGG 306", "Engineering Design 1 (Design Principles and Methods)", 3, "ENGG 302"),
        ("ENGG 307", "Instrumentation and Control Systems", 3, "ENGG 205, MATH 201"), _lab("ENGG 307", "Instrumentation and Control Systems", "ENGG 205 L"),
        ("ENGG 308", "Engineering Laws, Contracts and Professional Practice", 3, NONE),
        ("ENGG 309", "Technopreneurship for Engineers", 3, "ENGG 203"),
        ("ENGG 310", "Engineering Elective 2", 3, "ENGG 305")]),
    _t(3, "Summer", [("ENGG 311", "Engineering Internship / On-the-Job Training (minimum 240 hours)", 3, "Regular 3rd Year standing")]),
    _t(4, "First Semester", [("ENGG 401", "Engineering Capstone Project 1", 3, "ENGG 304, ENGG 306"),
        ("ENGG 402", "Engineering Elective 3", 3, "ENGG 310"),
        ("ENGG 403", "Engineering Seminar and Industry Colloquium", 1, "ENGG 311"),
        ("ENGG 404", "Systems Engineering and Quality Management", 3, "ENGG 302")]),
    _t(4, "Second Semester", [("ENGG 405", "Engineering Capstone Project 2", 3, "ENGG 401"),
        ("ENGG 406", "Engineering Elective 4", 3, "ENGG 402"),
        ("ENGG 407", "Engineering Project Management and Feasibility Studies", 3, "ENGG 401")]),
]

# ---- B.Eng. Bachelor of Engineering: practice- and design-oriented (more workshop, design studio, lab) ----
CURRICULUM_BENG = [
    _t(1, "First Semester", [_ge(101), _ge(105),
        ("MATH 101", "Engineering Calculus 1", 3, NONE),
        ("PHYS 101", "Engineering Physics 1 (Mechanics)", 3, NONE), _lab("PHYS 101", "Engineering Physics 1 (Mechanics)"),
        ("BENG 101", "Introduction to Engineering Practice", 2, NONE),
        ("BENG 102", "Engineering Graphics and Technical Drawing", 2, NONE),
        ("BENG 103", "Workshop Practice and Fabrication", 2, NONE),
        _pe(1), _nstp(1)]),
    _t(1, "Second Semester", [_ge(102), _ge(104),
        ("MATH 102", "Engineering Calculus 2", 3, "MATH 101"),
        ("CHEM 101", "Engineering Chemistry", 3, NONE), _lab("CHEM 101", "Engineering Chemistry"),
        ("BENG 104", "Programming and Computational Tools for Engineers", 3, NONE),
        ("BENG 105", "Computer-Aided Design (CAD)", 2, "BENG 102"),
        _pe(2), _nstp(2)]),
    _t(2, "First Semester", [_ge(106),
        ("MATH 201", "Differential Equations and Linear Algebra for Engineers", 3, "MATH 102"),
        ("PHYS 201", "Engineering Physics 2 (Electricity and Magnetism)", 3, "PHYS 101"), _lab("PHYS 201", "Engineering Physics 2 (Electricity and Magnetism)", "PHYS 101"),
        ("BENG 201", "Statics and Dynamics", 3, "MATH 102, PHYS 101"),
        ("BENG 202", "Engineering Materials and Manufacturing Processes", 3, "CHEM 101"), _lab("BENG 202", "Engineering Materials and Manufacturing Processes", "CHEM 101 L"),
        ("BENG 203", "Engineering Design Studio 1", 2, "BENG 103, BENG 105"),
        _pe(3)]),
    _t(2, "Second Semester", [_ge(107),
        ("MATH 202", "Engineering Statistics and Probability", 3, "MATH 102"),
        ("BENG 204", "Mechanics of Materials", 3, "BENG 201"), _lab("BENG 204", "Mechanics of Materials", "BENG 201"),
        ("BENG 205", "Thermodynamics and Heat Transfer", 3, "PHYS 101, MATH 102"),
        ("BENG 206", "Electrical Circuits and Electronics", 3, "PHYS 201"), _lab("BENG 206", "Electrical Circuits and Electronics", "PHYS 201"),
        ("BENG 207", "Engineering Design Studio 2", 2, "BENG 203"),
        _pe(4)]),
    _t(3, "First Semester", [_ge(108),
        ("BENG 301", "Fluid Mechanics and Hydraulics", 3, "BENG 201"), _lab("BENG 301", "Fluid Mechanics and Hydraulics", "BENG 201"),
        ("BENG 302", "Numerical Methods and Engineering Simulation", 3, "MATH 201, BENG 104"),
        ("BENG 303", "Control Systems and Automation", 3, "BENG 206, MATH 201"), _lab("BENG 303", "Control Systems and Automation", "BENG 206 L"),
        ("BENG 304", "Engineering Economy and Cost Estimation", 3, "MATH 102"),
        ("BENG 305", "Engineering Design Studio 3", 2, "BENG 207")]),
    _t(3, "Second Semester", [_ge(109),
        ("BENG 306", "Industrial Safety, Health and Environment", 3, NONE),
        ("BENG 307", "Engineering Management and Quality Assurance", 3, "BENG 304"),
        ("BENG 308", "Engineering Research Methods", 3, "MATH 202"),
        ("BENG 309", "Specialization Elective 1", 3, "BENG 303"),
        ("BENG 310", "Professional Ethics, Laws and Contracts for Engineers", 3, NONE)]),
    _t(3, "Summer", [("BENG 311", "Engineering Practice / Industrial Training (minimum 300 hours)", 6, "Completed Third Year courses")]),
    _t(4, "First Semester", [("BENG 401", "Final Year Engineering Project 1", 3, "BENG 305, BENG 308"),
        ("BENG 402", "Specialization Elective 2", 3, "BENG 309"),
        ("BENG 403", "Sustainable and Ethical Engineering Practice", 3, "BENG 306"),
        ("BENG 404", "Engineering Entrepreneurship and Innovation", 3, "BENG 304")]),
    _t(4, "Second Semester", [("BENG 405", "Final Year Engineering Project 2", 3, "BENG 401"),
        ("BENG 406", "Specialization Elective 3", 3, "BENG 402"),
        ("BENG 407", "Professional Engineering Practice Seminar", 1, "BENG 311")]),
]

SUGGESTED_NOTE = "Suggested plan modeled on the CHED framework ({ref})."

PROGRAMS = {
    "BSIT": {"short": "BSIT", "name": "Bachelor of Science in Information Technology",
             "reference": "Revised June 2018 · Per CMO no. 25, s. 2015 · Compliant with CMO no. 57, s. 2017",
             "draft_all": False, "draft_note": "Fourth Year was not part of the supplied curriculum pages. Confirm or replace it with the official Fourth Year before using it for enrollment.",
             "blocks": CURRICULUM_BSIT},
    "BSCS": {"short": "BSCS", "name": "Bachelor of Science in Computer Science",
             "reference": "Per CMO no. 25, s. 2015 · GE per CMO no. 20, s. 2013 and CMO no. 4, s. 2018",
             "draft_all": True, "draft_note": SUGGESTED_NOTE.format(ref="CMO no. 25, s. 2015"), "blocks": CURRICULUM_BSCS},
    "BSEng": {"short": "B.S. Engineering", "name": "Bachelor of Science in Engineering",
              "reference": "CHED engineering framework (math, basic sciences, engineering sciences) · GE per CMO no. 20, s. 2013",
              "draft_all": True, "draft_note": SUGGESTED_NOTE.format(ref="CHED engineering framework; choose the exact discipline, e.g. Civil, Electrical or Mechanical, and replace the electives"), "blocks": CURRICULUM_BSENG},
    "BEng": {"short": "B.Eng.", "name": "Bachelor of Engineering",
             "reference": "Practice- and design-oriented engineering plan · GE per CMO no. 20, s. 2013",
             "draft_all": True, "draft_note": SUGGESTED_NOTE.format(ref="CHED engineering framework; choose the exact discipline and replace the specialization electives"), "blocks": CURRICULUM_BENG},
    "BSEntrep": {"short": "BS Entrep", "name": "Bachelor of Science in Entrepreneurship",
                 "reference": "Per CMO no. 18, s. 2017 · GE per CMO no. 20, s. 2013 and CMO no. 4, s. 2018",
                 "draft_all": True, "draft_note": SUGGESTED_NOTE.format(ref="CMO no. 18, s. 2017"), "blocks": CURRICULUM_BSENTREP},
}
DEFAULT_PROGRAM = "BSIT"
