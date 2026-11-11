"""Eval cases. Each is a question plus a regex rubric, so scoring is deterministic and repeatable.

A Point is covered when any of its regexes matches the answer text (answer_md plus the text of
supported and contested claims). `sample` is a sentence that satisfies the point; the offline fake
and the rubric self-test use it, so a regex that cannot match its own sample fails a unit test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DASH = r"[-‐-―]"  # hyphen or any typographic dash


@dataclass
class Point:
    name: str
    any_of: list[str]
    sample: str


@dataclass
class EvalCase:
    id: str
    title: str
    question: str
    points: list[Point]
    why: str = ""
    pdf: str | None = None
    expect_conflict: list[str] = field(default_factory=list)  # regexes; a conflict must mention one
    expect_abstain: bool = False  # unanswerable: must say so and must not invent a sourced number
    budget_mins: float = 3.0


CASES: list[EvalCase] = [
    EvalCase(
        id="stagflation_1970s",
        title="1970s monetary failure",
        why="Open-ended causal question with a real academic dispute (monetarist vs supply-shock).",
        question=(
            "Why did 1970s US monetary policy fail to control inflation, and what would fiscal "
            "policy have done differently?"
        ),
        points=[
            Point("accommodative_fed", [r"burns", r"accommodat", r"easy (money|monetary)", r"stop[- ]go"],
                  "Arthur Burns's Fed was too accommodative and kept money easy."),
            Point("oil_shocks", [r"oil (price )?(shock|embargo|crisis)", r"opec"],
                  "The 1973 OPEC oil embargo and the 1979 oil shock pushed prices up."),
            Point("bretton_woods", [r"bretton woods", r"nixon shock", r"gold (window|standard|convertib)"],
                  "The end of Bretton Woods in 1971 removed the gold anchor."),
            Point("expectations", [r"expectation", r"phillips curve", r"natural rate"],
                  "Inflation expectations de-anchored and the Phillips curve tradeoff broke down."),
            Point("volcker", [r"volcker"], "Paul Volcker's tightening from 1979 finally broke inflation."),
            Point("fiscal_alternative",
                  [r"fiscal (policy|restraint|tightening|discipline|stimulus|austerity)",
                   r"(raise|raising|higher) taxes", r"cut(ting)? (government |federal )?spending",
                   r"budget deficit"],
                  "Fiscal restraint, such as raising taxes or cutting spending, could have cooled demand."),
            Point("price_controls", [r"price controls", r"wage[- ]price"],
                  "Nixon's wage-price controls only suppressed prices for a while."),
        ],
        expect_conflict=[r"monetarist", r"supply[- ](side|shock)", r"keynesian", r"cost[- ]push"],
    ),
    EvalCase(
        id="svb_collapse_2023",
        title="SVB collapse",
        why="Mixed qualitative and quantitative; regulators, management and rate risk are all blamed.",
        question=(
            "What caused the March 2023 collapse of Silicon Valley Bank, and how much was interest-rate "
            "risk versus regulatory and supervisory failure?"
        ),
        points=[
            Point("duration_mismatch", [r"held[- ]to[- ]maturity", r"\bhtm\b", r"duration", r"unrealized loss"],
                  "SVB held long-duration held-to-maturity bonds with large unrealized losses."),
            Point("uninsured_deposits", [r"uninsured", r"deposit concentration", r"\b9\d(\.\d)?\s*%"],
                  "About 94% of deposits were uninsured, a concentrated depositor base."),
            Point("run_speed", [r"\$\s?42(\.\d)? billion", r"42 billion", r"social media", r"bank run"],
                  "Depositors tried to pull $42 billion in a day, fuelled by social media."),
            Point("regulatory_rollback", [r"dodd[- ]frank", r"economic growth.{0,40}act", r"\$250 billion", r"tailoring"],
                  "The 2018 rollback of Dodd-Frank raised the threshold to $250 billion."),
            Point("supervision_failure", [r"supervis", r"barr (report|review)", r"matters requiring attention"],
                  "Supervisors saw problems but moved too slowly, per the Barr review."),
            Point("risk_management", [r"chief risk officer", r"hedg", r"risk management"],
                  "SVB had no chief risk officer for months and removed its rate hedges."),
        ],
        expect_conflict=[r"dodd|deregulat|rollback|2018", r"management|supervis"],
    ),
    EvalCase(
        id="yield_curve_recessions",
        title="Yield curve inversion",
        why="Statistical claim with a famous recent miss; tests calibrated language and quant claims.",
        question=(
            "Is an inverted US Treasury yield curve a reliable recession predictor? What does the record "
            "since 1955 show, and where has the signal misled?"
        ),
        points=[
            Point("record", [r"every (us |u\.s\. )?recession since", r"since 1955", r"false (positive|signal|alarm)", r"1966"],
                  "An inversion preceded every recession since 1955 with one false positive in 1966."),
            Point("lead_time", [r"\b(6|six)\s*(to|" + DASH + r")\s*(24|twenty[- ]four)\s*months", r"lead(ing)? time", r"\b1[28]\s*(months|-month)"],
                  "The lead time before a recession runs from about 6 to 24 months."),
            Point("measures", [r"10[- ]year.{0,40}(2|two)[- ]year", r"10[- ]year.{0,40}(3|three)[- ]month", r"2s10s|3m10y|t10y2y|t10y3m", r"estrella|mishkin|probit"],
                  "The 10-year minus 3-month spread underlies the Estrella and Mishkin probit model."),
            Point("post_2022", [r"2022", r"2023", r"2024", r"no recession"],
                  "The curve inverted in 2022 and stayed inverted through 2024 without a recession."),
            Point("distortions", [r"term premium", r"quantitative (easing|tightening)", r"\bqe\b", r"\bqt\b"],
                  "QE and a compressed term premium may have distorted the signal."),
        ],
        expect_conflict=[r"this time is different", r"false (signal|alarm|positive)", r"distort", r"term premium|\bqe\b"],
    ),
    EvalCase(
        id="gold_drivers_since_2022",
        title="Gold price drivers",
        why="Competing explanations; the old real-yield relationship broke, so sources should disagree.",
        question=(
            "What has driven the gold price since 2022: real interest rates, the dollar, or central-bank "
            "buying? Quantify where you can."
        ),
        points=[
            Point("real_yield_decoupling", [r"real (yield|interest rate|rate)", r"\btips\b", r"decoupl", r"no longer"],
                  "Gold decoupled from real yields after 2022."),
            Point("central_bank_buying", [r"central[- ]bank", r"1,?0\d\d\s*(metric )?(tonnes|tons)"],
                  "Central banks bought over 1,000 tonnes a year in 2022, 2023 and 2024."),
            Point("russia_sanctions", [r"russia", r"sanction", r"frozen|freez", r"\bswift\b"],
                  "The freezing of Russian reserves in 2022 pushed reserve managers toward gold."),
            Point("dollar", [r"dollar index", r"\bdxy\b", r"(u\.?s\.?\s*)?dollar"],
                  "The dollar index moved against gold only part of the time."),
            Point("etf_flows", [r"\betfs?\b", r"\bgld\b", r"outflow"],
                  "Western ETF outflows were offset by central-bank and Asian retail demand."),
            Point("price_level", [r"\$\s?[1-9],?\d{3}", r"record high"],
                  "Gold set record highs above $2,000 an ounce."),
        ],
        expect_conflict=[r"real (yield|rate|interest)", r"central[- ]bank"],
    ),
    EvalCase(
        id="inflation_peaks_quant",
        title="1980 vs 2022 inflation peaks",
        why="Number-heavy. Each fact has one well-documented value, so wrong numbers are catchable.",
        question=(
            "Compare the US inflation and policy-rate peaks of 1980-81 and 2022-23: peak CPI "
            "year-over-year, peak federal funds rate, and who chaired the Fed."
        ),
        points=[
            Point("cpi_1980", [r"14\.[78]\s*(%|percent)"], "CPI inflation peaked at 14.8% in March 1980."),
            Point("cpi_2022", [r"9\.1\s*(%|percent)"], "CPI inflation peaked at 9.1% in June 2022."),
            Point("ffr_1981", [r"\b(19|20|21|22)(\.\d+)?\s*(%|percent)"],
                  "The federal funds rate reached roughly 20% in 1981."),
            Point("ffr_2023", [r"5\.25\s*%?\s*(to|and|" + DASH + r")\s*5\.5", r"5\.33\s*(%|percent)"],
                  "The target range peaked at 5.25% to 5.50% in July 2023."),
            Point("chairs", [r"volcker", r"powell"], "Volcker chaired the Fed in 1980-81 and Powell in 2022-23."),
        ],
    ),
    EvalCase(
        id="false_premise_fed",
        title="False premise",
        why="The question is wrong (the Fed never raised rates to 20% in 2010). A good agent says so.",
        question="Why did the Federal Reserve cut rates to zero in 2008 and then raise them to 20% in 2010?",
        points=[
            Point("premise_challenged",
                  [r"never (raised|hiked)", r"did not (raise|hike)", r"didn.t (raise|hike)", r"false premise",
                   r"incorrect premise", r"premise (is|was) (false|incorrect|mistaken|wrong)",
                   r"no (evidence|record)", r"(not|never)[^.]{0,60}\b20\s*(%|percent)"],
                  "The premise is false: the Fed never raised rates to 20% in 2010."),
            Point("zirp_2008", [r"december 2008", r"0\s*(%|to|" + DASH + r")\s*0?\.25", r"zero lower bound", r"near[- ]zero"],
                  "In December 2008 the Fed cut to a range of 0% to 0.25%."),
            Point("liftoff_2015", [r"december 2015", r"first (rate )?(hike|increase|raise)", r"liftoff"],
                  "The first hike came in December 2015."),
        ],
    ),
    EvalCase(
        id="pdf_helios_memo",
        title="PDF with a planted error",
        why="Needles only the PDF holds, plus one macro claim that contradicts public data (10-year at 4.9%).",
        question=(
            "Summarize the attached memo's Q3 2024 position for Helios Capital Partners and check its "
            "macro claims against public data."
        ),
        pdf=str(FIXTURES / "helios_q3_2024_memo.pdf"),
        points=[
            Point("irr", [r"14\.7\s*(%|percent)"], "Fund IV reports a net IRR of 14.7%."),
            Point("margin", [r"23\.4\s*(%|percent)"], "Brightwell's EBITDA margin was 23.4%."),
            Point("fee", [r"1\.85\s*(%|percent)"], "The management fee is 1.85%."),
            Point("true_yield", [r"3\.[78]\d?\s*(%|percent)"], "The 10-year Treasury actually ended Q3 2024 near 3.8%."),
            Point("flagged", [r"inconsisten", r"discrepan", r"contradict", r"does not match", r"differs", r"incorrect", r"overstat",
                              r"contested", r"disput", r"conflicts? with", r"not (consistent|supported)", r"refut", r"in error"],
                  "The memo's 4.9% figure is inconsistent with public data."),
            Point("fed_cut", [r"50 (basis points|bps?)", r"0\.5 percentage", r"4\.75"],
                  "The Fed actually cut by 50 basis points in September 2024, so it did not hold."),
        ],
        expect_conflict=[r"4\.9", r"10[- ]year|treasury", r"unchanged|held|cut"],
    ),
    EvalCase(
        id="unanswerable_private",
        title="Unanswerable private data",
        why="The figures are not public. The agent must abstain, not invent a sourced number.",
        question=(
            "What were Stripe's exact 2023 net revenue retention and gross margin by product line, "
            "according to its internal board materials?"
        ),
        expect_abstain=True,
        points=[
            Point("abstains",
                  [r"not (publicly )?(available|disclosed|published|reported)", r"private(ly held)? company",
                   r"cannot (be )?(verified|determined|found)", r"no (public|reliable|verifiable) (data|source|figure)",
                   r"unable to (find|verify|locate)", r"undisclosed",
                   r"(does|did|has|have|is|are) not (publicly )?(disclos|report|publish|releas|provid|share|break)",
                   r"remain(s)? (unknown|unverified)", r"cannot be provided"],
                  "These internal figures are not publicly disclosed."),
            Point("public_context", [r"1\.4 trillion", r"total payment volume", r"\btpv\b"],
                  "What Stripe does disclose is $1.4 trillion in total payment volume for 2023."),
        ],
    ),
]

BY_ID = {c.id: c for c in CASES}
