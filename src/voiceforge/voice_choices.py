"""Curated Edge voices, sorted by what a person actually wants to pick.

The Microsoft catalogue has hundreds of entries, which is great when you know
the exact short name and terrible when you just want "a male voice" or "that
Ava voice". This module is the small, human list behind the Speak tab's quick
buttons and the voice chooser. It is deliberately Qt-free so the CLI, tests and
other front-ends can use the same labels.

The full fetched catalogue is still authoritative: ``merge_choices`` adds any
voice that is not in the curated list and infers a readable name from its short
name. Curated entries only supply a friendly label, a gender and a short note.
"""

from __future__ import annotations

from dataclasses import dataclass

MALE = "Male"
FEMALE = "Female"
OTHER = "Other"


@dataclass(frozen=True)
class VoiceChoice:
    short: str
    name: str
    gender: str
    locale: str
    note: str = ""
    featured: bool = False

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.gender and self.gender != OTHER:
            parts.append(self.gender)
        if self.locale:
            parts.append(self.locale)
        return " - ".join(parts)

    @property
    def detailed_label(self) -> str:
        if self.note:
            return f"{self.label}  ({self.note})"
        return self.label


# The voices worth putting in front of someone immediately. Andrew is the
# current default male voice; Ava is the featured female. The rest cover the
# usual tastes and the main English accents.
CURATED: tuple[VoiceChoice, ...] = (
    VoiceChoice("en-US-AndrewMultilingualNeural", "Andrew", MALE, "en-US",
                "warm and natural - the default", featured=True),
    VoiceChoice("en-US-AvaMultilingualNeural", "Ava", FEMALE, "en-US",
                "expressive and natural - the featured female", featured=True),
    VoiceChoice("en-US-EmmaMultilingualNeural", "Emma", FEMALE, "en-US",
                "cheerful and friendly", featured=True),
    VoiceChoice("en-US-BrianMultilingualNeural", "Brian", MALE, "en-US",
                "confident and conversational", featured=True),

    VoiceChoice("en-US-ChristopherNeural", "Christopher", MALE, "en-US",
                "deep and steady"),
    VoiceChoice("en-US-EricNeural", "Eric", MALE, "en-US", "calm and clear"),
    VoiceChoice("en-US-GuyNeural", "Guy", MALE, "en-US", "bright news-reader"),
    VoiceChoice("en-US-RogerNeural", "Roger", MALE, "en-US",
                "lively and animated"),
    VoiceChoice("en-GB-RyanNeural", "Ryan", MALE, "en-GB", "crisp British"),
    VoiceChoice("en-GB-ThomasNeural", "Thomas", MALE, "en-GB",
                "formal British"),
    VoiceChoice("en-AU-WilliamMultilingualNeural", "William", MALE, "en-AU",
                "Australian"),
    VoiceChoice("en-CA-LiamNeural", "Liam", MALE, "en-CA", "Canadian"),
    VoiceChoice("en-IE-ConnorNeural", "Connor", MALE, "en-IE", "Irish"),
    VoiceChoice("en-IN-PrabhatNeural", "Prabhat", MALE, "en-IN",
                "Indian English"),

    VoiceChoice("en-US-AriaNeural", "Aria", FEMALE, "en-US",
                "polished news-reader"),
    VoiceChoice("en-US-JennyNeural", "Jenny", FEMALE, "en-US",
                "helpful assistant"),
    VoiceChoice("en-US-MichelleNeural", "Michelle", FEMALE, "en-US",
                "soft and warm"),
    VoiceChoice("en-GB-SoniaNeural", "Sonia", FEMALE, "en-GB",
                "British, elegant"),
    VoiceChoice("en-GB-LibbyNeural", "Libby", FEMALE, "en-GB",
                "British, youthful"),
    VoiceChoice("en-AU-NatashaNeural", "Natasha", FEMALE, "en-AU",
                "Australian"),
    VoiceChoice("en-CA-ClaraNeural", "Clara", FEMALE, "en-CA", "Canadian"),
    VoiceChoice("en-IE-EmilyNeural", "Emily", FEMALE, "en-IE", "Irish"),
    VoiceChoice("en-IN-NeerjaNeural", "Neerja", FEMALE, "en-IN",
                "Indian English"),

    # Useful character voices. They are still ordinary Edge voices, just with
    # a smaller, younger or more theatrical sound.
    VoiceChoice("en-US-AnaNeural", "Ana", OTHER, "en-US", "child voice"),
    VoiceChoice("en-US-SteffanNeural", "Steffan", MALE, "en-US",
                "mature narrator"),
    VoiceChoice("en-GB-MaisieNeural", "Maisie", OTHER, "en-GB", "child voice"),
)

FEATURED = tuple(choice for choice in CURATED if choice.featured)
BY_SHORT = {choice.short: choice for choice in CURATED}
BY_NAME = {choice.name.lower(): choice for choice in CURATED}

# Catalogue voices that are not in the curated shortlist still get a useful
# gender in the chooser. These are the common Edge first names, not a
# definitive list; unknown names become "Other" rather than being hidden.
FEMALE_NAMES = {
    "Aria", "Ava", "Clara", "Emily", "Emma", "Jenny", "Libby", "Maisie",
    "Michelle", "Nancy", "Natasha", "Neerja", "Sara", "Sonia", "Ana",
    "Alba", "Amala", "Amber", "Ashley", "Cora", "Elizabeth", "Eloise",
    "Evelyn", "Fiona", "HiuMaan", "HiuGaai", "Kalpana", "Katja", "Luna",
    "Mia", "Molly", "Nabanita", "Niamh", "Olivia", "Phoebe", "Seraphina",
    "Shruti", "Swara", "Tania", "Xiaoxiao", "Xiaoyi", "Yan", "Yunxi",
    "Zari", "Zofia",
}
MALE_NAMES = {
    "Andrew", "Brian", "Christopher", "Connor", "Duncan", "Eric", "Guy",
    "Jason", "Liam", "Luke", "Mitchell", "Prabhat", "Roger", "Ryan", "Sam",
    "Steffan", "Thomas", "Tony", "Wayne", "William", "Aarav", "Achille",
    "Alain", "Alex", "Ardi", "Asad", "Daan", "Dmitry", "Eitan", "Finn",
    "Gerard", "Harry", "Jacob", "Jamal", "Jan", "Kai", "Killian", "Liam",
    "Mads", "Mateo", "Nestor", "Nicolas", "Noah", "Ravi", "Rizwan", "Sander",
    "Sven", "Thomas", "Tobias", "Tom", "Ulrich", "Victor", "Wilson",
}


def parse_short(short: str) -> tuple[str, str]:
    """Return (readable name, locale) from an Edge short name.

    ``en-US-AndrewMultilingualNeural`` -> ``("Andrew", "en-US")``.
    Unknown shapes fall back to the whole short name, which is still better
    than showing an empty row.
    """
    short = (short or "").strip()
    if not short:
        return "", ""
    parts = short.split("-")
    locale = "-".join(parts[:2]) if len(parts) >= 2 else ""
    stem = parts[2] if len(parts) >= 3 else short
    for suffix in ("MultilingualNeural", "Multilingual", "Neural"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem or short, locale


def gender_for(short: str) -> str:
    choice = BY_SHORT.get(short)
    if choice is not None:
        return choice.gender
    name, _locale = parse_short(short)
    if name in FEMALE_NAMES:
        return FEMALE
    if name in MALE_NAMES:
        return MALE
    return OTHER


def describe(short: str) -> VoiceChoice:
    """A curated entry when we have one, otherwise a readable inference."""
    choice = BY_SHORT.get(short)
    if choice is not None:
        return choice
    name, locale = parse_short(short)
    return VoiceChoice(short, name or short, gender_for(short), locale)


def curated(gender: str | None = None,
            featured_only: bool = False) -> list[VoiceChoice]:
    """The shortlist, in a deliberate order."""
    choices = [choice for choice in CURATED
               if not featured_only or choice.featured]
    if gender and gender != "All":
        choices = [choice for choice in choices if choice.gender == gender]
    return list(choices)


def merge_choices(names: list[str] | tuple[str, ...] | None = None) -> list[VoiceChoice]:
    """Combine a fetched name list with the curated shortlist.

    Curated order is preserved first (featured voices at the top), then the
    remaining catalogue entries are sorted by gender, locale and name. Entries
    are deduplicated by short name.
    """
    seen: set[str] = set()
    merged: list[VoiceChoice] = []
    for choice in CURATED:
        if not names or choice.short in names:
            merged.append(choice)
            seen.add(choice.short)
    extras: list[VoiceChoice] = []
    for short in names or ():
        short = (short or "").strip()
        if not short or short in seen:
            continue
        seen.add(short)
        extras.append(describe(short))
    order = {MALE: 0, FEMALE: 1, OTHER: 2}
    extras.sort(key=lambda item: (order.get(item.gender, 9),
                                  item.locale, item.name.lower()))
    return merged + extras


def all_names(names: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Every short name for a completer: fetched list plus curated voices."""
    result: list[str] = []
    for short in names or ():
        if short and short not in result:
            result.append(short)
    for choice in CURATED:
        if choice.short not in result:
            result.append(choice.short)
    return result
