import json
import re

import pytest

from humanizer import rules
from humanizer.rules import MK, PH_C, PH_O, RuleHumanizer, humanize, load_dictionary

SAMPLES = [
    """In today's world, technology plays a crucial role in education. Furthermore, it is important to note that students utilize digital tools on a daily basis. Teachers at Lincoln High School reported a 23% increase in engagement in March 2024. This is a testament to the power of innovation. Moreover, it is clear that these tools do not replace teachers. In conclusion, technology plays a crucial role in modern education.

Additionally, schools must navigate the complexities of funding. The district spent $1.2 million on laptops. Dr. Maria Chen said "we cannot utilize what we cannot afford." Additionally, many parents do not have reliable internet at home.""",

    """Climate change is one of the most pressing issues of our time. It is a complex phenomenon that affects ecosystems, economies, and communities. Scientists at NASA have recorded a 1.1°C rise since 1880. Furthermore, sea levels rose 8–9 inches between 1880 and 2020. It is essential that governments take action in a timely manner. Moreover, individuals can leverage their choices to reduce emissions.

Furthermore, the Paris Agreement, signed on 12 December 2015, aims to limit warming to 1.5°C. The United Nations reports that 196 parties have joined. However, progress has been slow. However, there is still hope for meaningful change.""",

    """Effective time management is crucial for success. It allows individuals to prioritize tasks, reduce stress, and achieve their goals. Research by Stanford University found that multitasking reduces productivity by up to 40%. Additionally, the Pomodoro Technique, developed by Francesco Cirillo in the late 1980s, utilizes 25-minute work intervals. It is worth noting that breaks are equally important. In order to succeed, one must utilize a comprehensive approach. Overall, effective time management is crucial for success.""",

    """The company's Q3 revenue was $4,250,000, up 12% from Q2. CEO John O'Brien stated that "growth will continue through 2025." The team, which includes engineers from Google and Microsoft, delivered the product on 03/15/2024. Visit https://example.com/report or email press@example.com for details. It is evident that the strategy is working. Thus, the board approved a budget of €3.5M for expansion.""",

    """Reading is a fundamental skill that plays a vital role in academic achievement. Students who read regularly develop a richer vocabulary, stronger comprehension, and better critical thinking. A 2019 study of 2,500 children in Ohio showed that those who read twenty minutes a day scored 15 points higher. Furthermore, reading fosters empathy and imagination. In addition, libraries serve as vital community hubs. To summarize, reading is a fundamental skill that is crucial for academic achievement.""",
]


def facts(text: str) -> set[str]:
    """Things that must survive: numbers, dates, quotes, URLs, emails, mid-sentence names."""
    out = set(re.findall(r"[$€£]?\d[\d,]*(?:\.\d+)?(?:%|°C|M\b)?", text))
    out |= set(re.findall(r'"[^"]*"|“[^”]*”', text))
    out |= set(re.findall(r"https?://\S+?(?=[\s,]|\.\s|$)|[\w.]+@[\w.]+\w", text))
    out |= set(re.findall(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", text))
    for m in re.finditer(r"\b[A-Z][\w'’-]*", text):
        before = text[: m.start()].rstrip(' "“(')
        if before and before[-1] not in ".!?\n:" and m.group() != "I":
            out.add(m.group())
    return out


@pytest.mark.parametrize("sample", range(len(SAMPLES)))
@pytest.mark.parametrize("strength", [0, 1, 2])
@pytest.mark.parametrize("tone", ["Casual", "Neutral", "Formal", "Student essay"])
def test_facts_names_numbers_dates_quotes_never_change(sample, strength, tone):
    text = SAMPLES[sample]
    want = facts(text)
    for seed in range(15):
        out = humanize(text, strength, tone, seed=seed).text
        missing = {f for f in want if f not in out}
        assert not missing, f"seed {seed} lost {missing}\n{out}"
        assert PH_O not in out and PH_C not in out and MK not in out


@pytest.mark.parametrize("seed", range(10))
def test_output_is_tidy(seed):
    for text in SAMPLES:
        out = humanize(text, 2, "Casual", seed=seed).text
        assert "  " not in out
        assert not re.search(r" [,.;:!?]", out)
        assert ",," not in out
        # every sentence starts with a capital letter, digit, symbol or quote
        for m in re.finditer(r"(?:^|[.!?]\s+)([^\s])", out, re.M):
            ch = m.group(1)
            assert not ch.islower(), f"lowercase sentence start near: {out[max(0, m.start() - 30):m.end() + 30]!r}"
        assert out.count("\n\n") == text.count("\n\n")  # paragraph structure kept


def test_quotes_are_untouched_even_with_dictionary_words():
    text = 'Furthermore, she said "we must utilize every crucial tool in order to win." We utilize tools.'
    for seed in range(10):
        out = humanize(text, 2, "Neutral", seed=seed).text
        assert '"we must utilize every crucial tool in order to win."' in out
        assert "We use tools." in out


def test_phrase_dictionary_replacements():
    out = humanize("We utilize this in order to delve into the data. Prior to launch, we tested it.", 2, seed=1).text
    assert "utilize" not in out and "in order to" not in out and "delve" not in out
    assert "Before launch" in out


def test_ai_openers_removed_at_heavy_strength():
    text = SAMPLES[0]
    for seed in range(10):
        out = humanize(text, 2, "Neutral", seed=seed).text
        for bad in ("Furthermore,", "Moreover,", "In today's world", "it is important to note", "It is important to note"):
            assert bad not in out


def test_contractions_applied_and_skipped_for_formal():
    text = "It is clear that we do not know. They are sure it is true and we are not."
    casual = humanize(text, 2, "Casual", seed=2).text
    assert "don't" in casual and ("They're" in casual or "it's" in casual)
    formal = humanize(text, 2, "Formal", seed=2).text
    assert "'" not in formal and "’" not in formal


def test_contractions_never_at_clause_end():
    for seed in range(20):
        out = humanize("I know what it is. You can see who they are. Here it is, finally.", 2, "Casual", seed=seed).text
        assert "what it is." in out and "who they are." in out and "Here it is," in out


def test_smart_apostrophes_follow_the_text():
    out = humanize("It’s late. It is not done and we do not care.", 2, "Casual", seed=1).text
    assert "'" not in out and "’" in out


def test_articles_agree_after_replacement():
    for seed in range(10):
        out = humanize("This is a crucial step. It was a comprehensive plan.", 2, seed=seed).text
        assert not re.search(r"\ba [aeiouAEIOU]", out) and not re.search(r"\ban [^aeiouAEIOU\W]", out)


def test_rhythm_breaks_up_uniform_sentences():
    text = ("The new library opened downtown last spring, and it quickly became a popular place for local students. "
            "The building has three floors of books and study rooms, and it stays open late on most weekdays. "
            "The staff organizes reading groups for children every week, and many parents bring their kids along. "
            "The city council approved more funding for the library in June, and the director plans new programs.")
    import statistics
    lens = lambda t: [len(s.split()) for s in re.split(r"(?<=[.!?])\s+", t.strip())]
    before = statistics.pstdev(lens(text)) / statistics.mean(lens(text))
    r = humanize(text, 2, "Neutral", seed=4)
    after = statistics.pstdev(lens(r.text)) / statistics.mean(lens(r.text))
    assert r.stats["splits"] + r.stats["merges"] >= 1
    assert after > before


def test_repeated_paragraph_openers_are_varied():
    text = "However, the plan failed.\n\nHowever, the team kept going.\n\nHowever, money ran out."
    out = humanize(text, 2, "Neutral", seed=3).text
    starts = [p.split()[0] for p in out.split("\n\n")]
    assert all(a != b for a, b in zip(starts, starts[1:])), out


def test_summary_sentence_that_repeats_the_opening_is_dropped():
    text = SAMPLES[2]
    out = humanize(text, 2, "Neutral", seed=1).text
    assert out.count("time management") < text.count("time management")
    light = humanize(text, 0, "Neutral", seed=1)
    assert light.stats["endings"] == 0


def test_ending_with_a_new_fact_is_kept():
    text = ("Solar power is growing fast. Panels are cheaper every year. Installers are busy. "
            "Solar power is growing fast, with 2,000 new jobs in 2023.")
    out = humanize(text, 2, seed=1).text
    assert "2,000" in out and "2023" in out


def test_light_touch_changes_less_than_heavy():
    import difflib
    text = "\n\n".join(SAMPLES)
    light = humanize(text, 0, seed=5).text
    heavy = humanize(text, 2, seed=5).text
    sim = lambda a, b: difflib.SequenceMatcher(None, a, b).ratio()
    assert sim(text, light) > sim(text, heavy)


def test_empty_and_whitespace():
    assert humanize("", 1).text == ""
    assert humanize("   \n\n  ", 1).text == "   \n\n  "


def test_dictionary_file_is_valid():
    d = json.loads(rules._resource("phrases.json").read_text(encoding="utf-8"))
    assert {"openers", "phrases"} <= set(d)
    for section in ("openers", "phrases"):
        for k, v in d[section].items():
            assert isinstance(v, list) and v, k
            assert all(isinstance(x, str) for x in v), k
    RuleHumanizer(load_dictionary())  # compiles


def test_no_thesaurus_spinning():
    """Words not in the dictionary are never swapped."""
    text = "The cat sat on the warm mat and watched the birds outside the window."
    for seed in range(10):
        assert humanize(text, 2, seed=seed).text == text


# ---------------------------------------------------------------- dashes, commas, plain words
DASHY = ('Remote work changed everything — and fast. Teams that once shared an office — often for years — now meet '
         'online. Productivity rose 12% between 2020–2022, and it held. She wrote "the office is dead — long live '
         'the office" in 2021. It works -- most of the time. The shift was simple – people wanted their time back.')


@pytest.mark.parametrize("strength", [0, 1, 2])
@pytest.mark.parametrize("tone", ["Casual", "Neutral", "Formal", "Student essay"])
def test_no_dashes_left_outside_quotes(strength, tone):
    for seed in range(8):
        for text in [DASHY] + SAMPLES:
            out = humanize(text, strength, tone, seed=seed).text
            outside = re.sub(r'"[^"]*"|“[^”]*”', "", out)
            assert "—" not in outside and "--" not in outside and " – " not in outside, out
            assert "2020–2022" in out or "2020–2022" not in text      # number ranges untouched
            assert '"the office is dead — long live the office"' in out or '"the office is dead' not in text


def test_dash_replacements_read_naturally():
    out = humanize(DASHY, 1, "Neutral", seed=1).text
    assert "(often for years)" in out                       # short paired aside -> parentheses
    assert "everything" in out and "It works, most of the time." in out and "held and she" not in out
    assert "People wanted their time back." in out or "people wanted their time back." in out


def test_fewer_commas():
    text = "\n\n".join(SAMPLES)
    for seed in range(5):
        for strength in (1, 2):
            out = humanize(text, strength, "Casual", seed=seed).text
            assert out.count(",") < text.count(","), out


def test_plain_words_replace_formal_ones():
    text = ("Approximately 40 individuals were able to purchase tickets. We need to ensure that the methodology "
            "is sufficient and demonstrates a variety of results.")
    out = humanize(text, 2, "Casual", seed=3).text
    for w in ("Approximately", "individuals", "were able to", "purchase", "ensure", "methodology", "sufficient", "demonstrates", "a variety of"):
        assert w not in out, (w, out)
    assert "40" in out


def test_formal_tone_skips_casual_swaps():
    from humanizer.rules import CASUAL_SWAPS
    text = "\n\n".join(SAMPLES) + " A variety of tools exist. You can delve into the data."
    for seed in range(10):
        out = humanize(text, 2, "Formal", seed=seed).text.lower()
        for c in CASUAL_SWAPS:
            if c not in text.lower():
                assert c not in out, (c, out)


def test_polish_cleans_without_restructuring():
    from humanizer.rules import RuleHumanizer
    text = "Furthermore, the plan works — mostly. We utilize it daily, and it helps. Teams like it, and they use it, and it scales."
    r = RuleHumanizer().polish(text, 1, "Neutral", seed=2)
    assert "—" not in r.text and "Furthermore" not in r.text and "utilize" not in r.text
    assert r.stats["splits"] == 0 and r.stats["merges"] == 0 and r.stats["endings"] == 0
