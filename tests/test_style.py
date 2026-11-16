import re

import pytest

from humanizer import rules, style
from tests.test_rules import SAMPLES, facts

CASUAL_ME = """I don't really get why people make such a big deal about mornings. I'm up at six most days and it's fine. Coffee helps. So does music.

My brother can't stand it though. He's the type who hits snooze five times and then acts like the world's ending. We've talked about it. It didn't help.

Honestly I think it's just habit. You do it enough and it stops feeling like a fight. And if it doesn't? Get a louder alarm. That's what I'd do anyway."""

FORMAL_ME = """The committee reviewed the proposal in considerable detail, and it concluded that the projected costs, although substantial, were justified by the anticipated benefits to the community, the school district, and the regional economy.

It is not, however, a decision that should be made without further consultation, since the residents who will be most affected have not yet had an adequate opportunity to express their views, concerns, and preferences in a formal setting.

We do not believe that the timeline, as currently written, allows for such consultation, and we therefore recommend that the vote be postponed until the spring, when a series of public meetings can be held."""


def test_profiles_measure_real_habits():
    c, f = style.analyze(CASUAL_ME), style.analyze(FORMAL_ME)
    assert c.contraction_rate > 0.7 and f.contraction_rate < 0.2
    assert c.avg_sentence_words < 10 < 25 < f.avg_sentence_words
    assert c.commas_per_sentence < f.commas_per_sentence
    assert c.short_sentence_share > 0.4
    assert c.starts_with_and_but > 0.08 and c.first_person > 2 and c.questions > 0
    assert any("contractions: almost always" in s or "contractions: often" in s for s in c.summary())
    assert "contractions: rarely" in f.summary()


def test_store_save_list_edit_delete(tmp_path):
    st = style.StyleStore(tmp_path / "styles.json")
    with pytest.raises(ValueError, match="at least"):
        st.save("tiny", "too short")
    item = st.save("Casual me", CASUAL_ME)
    again = style.StyleStore(tmp_path / "styles.json")          # persisted
    listed = again.list()
    assert listed[0]["name"] == "Casual me" and listed[0]["words"] > 60 and listed[0]["summary"]
    again.save("Renamed", CASUAL_ME, sid=item.id)
    assert [i["name"] for i in style.StyleStore(tmp_path / "styles.json").list()] == ["Renamed"]
    again.delete(item.id)
    assert style.StyleStore(tmp_path / "styles.json").list() == []


def _contractions(t):
    return len(re.findall(r"\b\w+['’](?:t|s|re|ve|ll|d|m)\b", t))


def test_rule_engine_follows_contraction_habit():
    text = "\n\n".join(SAMPLES)
    casual, formal = style.analyze(CASUAL_ME), style.analyze(FORMAL_ME)
    c = sum(_contractions(rules.humanize(text, 2, "Neutral", seed=s, style=casual).text) for s in range(5))
    f = sum(_contractions(rules.humanize(text, 2, "Neutral", seed=s, style=formal).text) for s in range(5))
    assert c > f * 3


def test_rule_engine_follows_comma_habit():
    text = "\n\n".join(SAMPLES)
    casual, formal = style.analyze(CASUAL_ME), style.analyze(FORMAL_ME)
    c = sum(rules.humanize(text, 1, "Neutral", seed=s, style=casual).text.count(",") for s in range(5))
    f = sum(rules.humanize(text, 1, "Neutral", seed=s, style=formal).text.count(",") for s in range(5))
    assert c < f


def test_short_sentence_writer_gets_more_splits():
    text = ("The new library opened downtown last spring, and it quickly became a popular place for local students. "
            "The building has three floors of books and study rooms, and it stays open late on most weekdays. "
            "The staff organizes reading groups for children every week, and many parents bring their kids along. "
            "The city council approved more funding for the library in June, and the director plans new programs.")
    casual, formal = style.analyze(CASUAL_ME), style.analyze(FORMAL_ME)
    c = sum(rules.humanize(text, 1, "Neutral", seed=s, style=casual).stats["splits"] for s in range(6))
    f = sum(rules.humanize(text, 1, "Neutral", seed=s, style=formal).stats["splits"] for s in range(6))
    assert c > f


@pytest.mark.parametrize("sample", range(len(SAMPLES)))
def test_facts_survive_with_a_style(sample):
    text = SAMPLES[sample]
    want = facts(text)
    for prof in (style.analyze(CASUAL_ME), style.analyze(FORMAL_ME)):
        for seed in range(8):
            out = rules.humanize(text, 2, "Casual", seed=seed, style=prof).text
            assert not {f for f in want if f not in out}


def test_formal_tone_still_wins_over_casual_style():
    out = rules.humanize("\n\n".join(SAMPLES), 2, "Formal", seed=1, style=style.analyze(CASUAL_ME)).text
    assert _contractions(out) <= _contractions("\n\n".join(SAMPLES))


def test_prompt_block_has_traits_and_examples():
    block = style.prompt_block(style.analyze(CASUAL_ME), CASUAL_ME)
    assert "<example>" in block and "words per sentence" in block and "never copy their content" in block
    assert "And, But or So" in block


def test_tiny_sample_is_ignored_by_rules():
    tiny = style.analyze("Hi there.")
    a = rules.humanize(SAMPLES[0], 2, seed=4).text
    b = rules.humanize(SAMPLES[0], 2, seed=4, style=tiny).text
    assert a == b
