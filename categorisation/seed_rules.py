from __future__ import annotations

"""
Starter CategorisationRule seed set, derived from Source 1 real data
(transaction-files/BankTransactions - CC.xlsx, 137 merchants, per the audit finding in
docs/product-requirements.md section 4.2 that it is highly self-consistent) and remapped from
the old flat category list to the finalized 16-category taxonomy (section 4.2). Patterns are
ordered longest-first so a more specific merchant name (e.g. UBER EATS) takes priority over a
shorter generic one (UBER) under the substring match_type.
"""

from sqlalchemy.orm import Session

from backend.models import CategorisationRule

SEED_RULES: list[dict] = [
    dict(pattern='QUINTESSENTIAL DIVING OCEAN FREE PTY. LTD.', match_type="substring", category='Travel & Holidays', subcategory='Attractions & Events', priority=1),
    dict(pattern='AUSTRALIAN ARMOUR & ARTILLERY MUSEUM', match_type="substring", category='Travel & Holidays', subcategory='Attractions & Events', priority=2),
    dict(pattern='MY INDIA INDIAN GROCERIES & SWEETS', match_type="substring", category='Groceries', subcategory=None, priority=3),
    dict(pattern='RICE PAPER SCISSORS ASIAN KITCHEN', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=4),
    dict(pattern='SURREY HILLS FAMILY DENTAL CLINIC', match_type="substring", category='Health & Medical', subcategory='Medical', priority=5),
    dict(pattern="ANDERSEN'S OF DENMARK ICE CREAM", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=6),
    dict(pattern="YAYA'S HELLENIC KITCHEN & BAR", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=7),
    dict(pattern='SKYRAIL RAINFOREST CABLEWAY', match_type="substring", category='Travel & Holidays', subcategory='Other', priority=8),
    dict(pattern='WILSON PHYSIOTHERAPY GROUP', match_type="substring", category='Health & Medical', subcategory='Medical', priority=9),
    dict(pattern='AUSTRALIAN PRODUCE STORE', match_type="substring", category='Groceries', subcategory=None, priority=10),
    dict(pattern='BENLEIGH VENDING SYSTEMS', match_type="substring", category='Groceries', subcategory=None, priority=11),
    dict(pattern='CAIRNS REGIONAL COUNCIL', match_type="substring", category='Government & Tax', subcategory='Government Fees', priority=12),
    dict(pattern='LUCY OI VIETNAMESE FOOD', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=13),
    dict(pattern="ROZZI'S ITALIAN CANTEEN", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=14),
    dict(pattern='HAVEN SPECIALTY COFFEE', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=15),
    dict(pattern='THE STATION FRESHWATER', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=16),
    dict(pattern='VILLA ROMANA TRATTORIA', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=17),
    dict(pattern='THE DAIRY BY MUNGALLI', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=18),
    dict(pattern='BCD CORPORATE TRAVEL', match_type="substring", category='Travel & Holidays', subcategory='Other', priority=19),
    dict(pattern='BOX HILL FISH MARKET', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=20),
    dict(pattern='RISE & BAKE CREPERIE', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=21),
    dict(pattern="TOBY'S ESTATE COFFEE", match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=22),
    # Broadened from 'CHILDFUND AUSTRALIA' (2026-09-25) -- that exact phrase, as seeded from Source
    # 1/CC, never matches the real recurring donation text on JC ("CHILDFUNDAU SURRY HILLS", no
    # space, no spelled-out "AUSTRALIA"). One shorter, still-distinctive pattern now covers both
    # real variants instead of two overlapping rules.
    dict(pattern='CHILDFUND', match_type="substring", category='Gifts & Donations', subcategory='Donations', priority=23),
    dict(pattern='NOA EAT DRINK SHARE', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=24),
    dict(pattern='WYNDHAM HOTEL GROUP', match_type="substring", category='Travel & Holidays', subcategory='Accommodation', priority=25),
    dict(pattern='AUSTRALIA THE GIFT', match_type="substring", category='Gifts & Donations', subcategory='Gifts', priority=26),
    # Fixed 2026-09-25 (Rohan's call, live): structurally a loan repayment financing a Wyndham
    # timeshare purchase -- was Services & Subscriptions/Other. Categorised consistently with the
    # AC property loan repayment rule (Loans & Finance/Loan Repayment) regardless of what asset the
    # loan is financing. Distinct from the real "WYNDHAM VACATION CLUBS ..." membership/usage fee,
    # which has no text rule of its own -- correctly resolved via the bank's own Category field
    # instead (categorisation/bank_category.py).
    dict(pattern='FINANCE BY WYNDHAM', match_type="substring", category='Loans & Finance', subcategory='Loan Repayment', priority=27),
    dict(pattern="HAIGH'S CHOCOLATES", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=28),
    dict(pattern='THAI NIGHT MARKETS', match_type="substring", category='Groceries', subcategory=None, priority=29),
    dict(pattern='TROPICAL PULSE QLD', match_type="substring", category='Travel & Holidays', subcategory='Attractions & Events', priority=30),
    dict(pattern='YARRA VALLEY WATER', match_type="substring", category='Housing', subcategory='Utility Bills', priority=31),
    # Removed 2026-09-25 (/code-review finding): this exact-outcome rule ('Insurance', None) is
    # now fully subsumed by the broader 'ALLIANZ' rule added below (priority 132) -- anything this
    # one matched, that one also matches, identically. Kept as one rule, not two that could drift.
    dict(pattern='CHEMIST WAREHOUSE', match_type="substring", category='Health & Medical', subcategory='Medical', priority=33),
    dict(pattern='CODE BLACK COFFEE', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=34),
    dict(pattern='MELBOURNE AIRPORT', match_type="substring", category='Travel & Holidays', subcategory='Flights', priority=35),
    dict(pattern="SOLLY'S SOUVENIRS", match_type="substring", category='Gifts & Donations', subcategory='Gifts', priority=36),
    dict(pattern='DARLING PAVILLON', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=37),
    dict(pattern='HEART FOUNDATION', match_type="substring", category='Gifts & Donations', subcategory='Donations', priority=38),
    dict(pattern='HERTZ CAR RENTAL', match_type="substring", category='Travel & Holidays', subcategory='Other', priority=39),
    dict(pattern="KINGS'S DUMPLING", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=40),
    dict(pattern='UNICEF AUSTRALIA', match_type="substring", category='Gifts & Donations', subcategory='Donations', priority=41),
    dict(pattern='WOOLWORTHS METRO', match_type="substring", category='Groceries', subcategory=None, priority=42),
    dict(pattern='BUTCHERS VALLEY', match_type="substring", category='Groceries', subcategory=None, priority=43),
    dict(pattern='CENTRAL GOURMET', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=44),
    dict(pattern='E. & S. TRADING', match_type="substring", category='Shopping', subcategory='Electronics & Technology', priority=45),
    dict(pattern='GENESIS FITNESS', match_type="substring", category='Health & Medical', subcategory='Gym & Fitness', priority=46),
    dict(pattern='KLOOK AUSTRALIA', match_type="substring", category='Travel & Holidays', subcategory='Other', priority=47),
    dict(pattern='MATER LOTTERIES', match_type="substring", category='Gifts & Donations', subcategory='Donations', priority=48),
    dict(pattern='SARAVANA BHAVAN', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=49),
    dict(pattern='TANK SIXTY FOUR', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=50),
    dict(pattern='URBAN PROVODORE', match_type="substring", category='Travel & Holidays', subcategory='Flights', priority=51),
    dict(pattern='COLONIAL FRESH', match_type="substring", category='Groceries', subcategory=None, priority=52),
    # Broadened from 'EVIE AUSTRALIA' and recategorised 2026-09-25 (Rohan's call, live): Evie is an
    # EV charging network -- a vehicle running cost (new Car/Charging subcategory), not a trip cost.
    # The original 'EVIE AUSTRALIA' text never matched the real recurring text seen on CC
    # ("EVIE NETWORKS BRISBANE"). A plain substring 'EVIE' also matches inside unrelated real words
    # ("REVIEW" contains "EVIE") -- /code-review finding -- so this is a word-boundary regex
    # instead, the one case in this file that needs it.
    dict(pattern=r'\bEVIE\b', match_type="regex", category='Car', subcategory='Charging', priority=53),
    dict(pattern='GOPI KA CHATKA', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=54),
    dict(pattern='GUZMAN Y GOMEZ', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=55),
    dict(pattern='LITTLE BANGKOK', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=56),
    dict(pattern='MORK CHOCOLATE', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=57),
    dict(pattern='MY MUSCLE CHEF', match_type="substring", category='Groceries', subcategory=None, priority=58),
    dict(pattern='PAPER REPUBLIC', match_type="substring", category='Gifts & Donations', subcategory='Gifts', priority=59),
    dict(pattern='STRIKE BOWLING', match_type="substring", category='Travel & Holidays', subcategory='Attractions & Events', priority=60),
    dict(pattern='WILSON PARKING', match_type="substring", category='Transport', subcategory='Parking & Tolls', priority=61),
    dict(pattern='ADOZEN ADOZEN', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=62),
    dict(pattern='MYKI PAYMENTS', match_type="substring", category='Transport', subcategory='Public Transport', priority=63),
    dict(pattern='POINT PARKING', match_type="substring", category='Transport', subcategory='Parking & Tolls', priority=64),
    dict(pattern='THE COURTYARD', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=65),
    dict(pattern='TRANSPORT NSW', match_type="substring", category='Transport', subcategory='Public Transport', priority=66),
    # Fixed 2026-09-25 (Rohan's call, live): a butcher shop, not Services & Subscriptions -- an
    # error in the *original* Source 1 seed data itself, present since J1, not introduced later.
    dict(pattern='HILLS MEATS', match_type="substring", category='Groceries', subcategory=None, priority=67),
    dict(pattern='KEBAB 2NITE', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=68),
    dict(pattern='RED CHUTNEY', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=69),
    dict(pattern='SOUL ORIGIN', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=70),
    dict(pattern='SRI DWARAKA', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=71),
    dict(pattern='SUPER SUSHI', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=72),
    dict(pattern='SWEET INDIA', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=73),
    dict(pattern='TPG TELECOM', match_type="substring", category='Services & Subscriptions', subcategory='Phone & Internet', priority=74),
    dict(pattern='BAO BAO GO', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=75),
    dict(pattern='FAREHARBOR', match_type="substring", category='Shopping', subcategory='Electronics & Technology', priority=76),
    dict(pattern='KEBAB YEAH', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=77),
    dict(pattern='THAILANDER', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=78),
    dict(pattern='WOOLWORTHS', match_type="substring", category='Groceries', subcategory=None, priority=79),
    dict(pattern='AXLE CAFE', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=80),
    dict(pattern='FISH PIER', match_type="substring", category='Groceries', subcategory=None, priority=81),
    dict(pattern='ICY SPICY', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=82),
    dict(pattern='PANTRY 15', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=83),
    dict(pattern='PAPPARICH', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=84),
    dict(pattern='RUBY CAFE', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=85),
    dict(pattern='SPOTLIGHT', match_type="substring", category='Shopping', subcategory='Homeware', priority=86),
    dict(pattern='UBER EATS', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=87),
    dict(pattern='7-ELEVEN', match_type="substring", category='Groceries', subcategory=None, priority=88),
    dict(pattern='CBP CAFE', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=89),
    dict(pattern='DOSA HUT', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=90),
    dict(pattern='EXPLOREN', match_type="substring", category='Travel & Holidays', subcategory='Other', priority=91),
    dict(pattern='FRUIBIES', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=92),
    dict(pattern='MEAT INN', match_type="substring", category='Groceries', subcategory=None, priority=93),
    dict(pattern='MEDIBANK', match_type="substring", category='Insurance', subcategory=None, priority=94),
    dict(pattern='ROTI BAR', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=95),
    dict(pattern='VODAFONE', match_type="substring", category='Services & Subscriptions', subcategory='Phone & Internet', priority=96),
    dict(pattern='WH SMITH', match_type="substring", category='Services & Subscriptions', subcategory='Media/Streaming', priority=97),
    dict(pattern="GRILL'D", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=98),
    dict(pattern='MAD MEX', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=99),
    dict(pattern="NANDO'S", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=100),
    dict(pattern='SAMSUNG', match_type="substring", category='Shopping', subcategory='Electronics & Technology', priority=101),
    dict(pattern='SCHNITZ', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=102),
    dict(pattern='SOFITEL', match_type="substring", category='Travel & Holidays', subcategory='Accommodation', priority=103),
    dict(pattern='ACENDA', match_type="substring", category='Insurance', subcategory=None, priority=104),
    dict(pattern='AMAZON', match_type="substring", category='Shopping', subcategory='Other', priority=105),
    dict(pattern='CHULHO', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=106),
    dict(pattern='HILTON', match_type="substring", category='Travel & Holidays', subcategory='Accommodation', priority=107),
    dict(pattern='QANTAS', match_type="substring", category='Travel & Holidays', subcategory='Flights', priority=108),
    dict(pattern="ROLL'D", match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=109),
    dict(pattern='SCONES', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=110),
    dict(pattern='SKYBUS', match_type="substring", category='Transport', subcategory='Taxis & Rideshare', priority=111),
    dict(pattern='SQUARE', match_type="substring", category='Shopping', subcategory='Other', priority=112),
    dict(pattern='YO WAY', match_type="substring", category='Cafes & Restaurants', subcategory='Restaurants & Takeaway', priority=113),
    dict(pattern='COLES', match_type="substring", category='Groceries', subcategory=None, priority=114),
    dict(pattern='HOYTS', match_type="substring", category='Travel & Holidays', subcategory='Attractions & Events', priority=115),
    dict(pattern='KMART', match_type="substring", category='Shopping', subcategory='Other', priority=116),
    dict(pattern='ETSY', match_type="substring", category='Shopping', subcategory='Other', priority=117),
    dict(pattern='MOSH', match_type="substring", category='Health & Medical', subcategory='Medical', priority=118),
    dict(pattern='MYER', match_type="substring", category='Shopping', subcategory='Other', priority=119),
    dict(pattern='OPSM', match_type="substring", category='Health & Medical', subcategory='Medical', priority=120),
    dict(pattern='SUMO', match_type="substring", category='Housing', subcategory='Utility Bills', priority=121),
    dict(pattern='UBER', match_type="substring", category='Transport', subcategory='Taxis & Rideshare', priority=122),
    dict(pattern='2CO', match_type="substring", category='Services & Subscriptions', subcategory='Other', priority=123),
    # Income coverage (added 2026-09-25) -- Source 1 (CC, a credit card) has zero income rows, so
    # the rules above have zero Income coverage. Harmless while the Claude fallback could still
    # recognise a salary/dividend credit; a real, silent gap now that the fallback is permanently
    # unavailable (no ANTHROPIC_API_KEY, ever -- docs/product-requirements.md §4.3.1): every real
    # income transaction landed in Miscellaneous, leaving GET /summary's total_income permanently
    # $0. These three patterns are real, unambiguous, bank/processor-labelled markers pulled from
    # the real AC/JC account data (transaction-files/) -- unlike the many genuinely ambiguous
    # credits in that same data (informal repayments, unlinked transfer legs), which correctly stay
    # in the needs-review queue rather than being force-categorised by a blanket rule.
    dict(pattern='SALARY/WAGES', match_type="substring", category='Income', subcategory='Salary', priority=124),
    dict(pattern='NAB INTERIM DIV', match_type="substring", category='Income', subcategory='Dividends & Distributions', priority=125),
    dict(pattern='EQUATEPLUS DIVIDENDS', match_type="substring", category='Income', subcategory='Dividends & Distributions', priority=126),
    # Real, unambiguous bank-labelled EMI/loan text (transaction-files/), same gap as above but on
    # the expense side -- reported live by Rohan.
    dict(pattern='LOAN REPAYMENT', match_type="substring", category='Loans & Finance', subcategory='Loan Repayment', priority=127),
    dict(pattern='INTEREST CHARGED', match_type="substring", category='Loans & Finance', subcategory='Loan Interest', priority=128),
    # Added 2026-09-25 after cross-referencing docs/AU COST - Manual categorisation.xlsx (13 years
    # of Rohan's own manual categorisation): "Arvan" is a family member, historically tracked as
    # its own recurring category (163 rows, 2012-2025) rather than left ambiguous. Subcategory left
    # unset -- real spending purpose varies (food, gym, trip, fees), unlike the historical log's
    # more granular per-purpose subcategories, which this project's current taxonomy has no exact
    # equivalent for.
    dict(pattern='ARVAN', match_type="substring", category='Kids & Family', subcategory=None, priority=133),
    # Confirmed genuine income by Rohan (not an internal transfer) -- his employer pays into a CBA
    # account not yet sampled in transaction-files/, which then moves to RC under this text; the
    # RC-side credit is the only record of that income currently visible to this system.
    dict(pattern='TRANSFER SALARY', match_type="substring", category='Income', subcategory='Salary', priority=129),
    # Rent from a real investment property (Rohan's call, 2026-09-25) -- see taxonomy.py's new
    # Rental Income subcategory. Keyed on the managing agent's name, which should generalise to
    # future rent credits from the same property/agent, not just this one truncated description.
    dict(pattern='THE APOSTOLI GRO', match_type="substring", category='Income', subcategory='Rental Income', priority=130),
    # Real, unambiguous merchants reported live by Rohan, each independently confirmed against the
    # real xlsx's own bank Category/Merchant Name columns (Donations/Oxfam Australia; Insurance/
    # Allianz Insurance) -- see the "using bank Category/Merchant Name" note in docs/next-steps.md.
    dict(pattern='OXFAM', match_type="substring", category='Gifts & Donations', subcategory='Donations', priority=131),
    # Subcategory left unset -- the bank's own Category ("Insurance") doesn't say which of Life/
    # TPD/Income Protection, Critical Illness, or Content (non-home) this policy is either.
    dict(pattern='ALLIANZ', match_type="substring", category='Insurance', subcategory=None, priority=132),
    # Deliberate low-priority, last-resort catch-all -- the bank's own Category for the real row
    # that prompted this ("435 BOURKE STREET CAFE MELBOURNE") is itself "Uncategorised", so there's
    # no bank signal to lean on for this one. Ordered after every specific named-merchant rule
    # above (priority 200, not adjacent to them) so a real coffee chain's own rule always wins
    # first; this only catches what nothing more specific already has.
    dict(pattern='CAFE', match_type="substring", category='Cafes & Restaurants', subcategory='Cafes & Coffee', priority=200),
]


def seed_rules_if_empty(session: Session) -> int:
    """Load the starter rule set on first run only (idempotent — a no-op once rules exist)."""
    if session.query(CategorisationRule.id).filter(CategorisationRule.source == "seeded").first() is not None:
        return 0
    for rule in SEED_RULES:
        session.add(CategorisationRule(source="seeded", is_active=True, **rule))
    session.commit()
    return len(SEED_RULES)
