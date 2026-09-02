"""Перевод кириллической фамилии в латиницу.

В таблице деканата фамилии записаны латиницей по загранпаспортной схеме
(«Iurchenko», «Shimanskaia»), а студент пишет боту кириллицей. Однозначного
обратного преобразования нет: «Ю» бывает `iu` и `yu`, «Я» — `ia` и `ya`.
Поэтому мы порождаем несколько вариантов написания и считаем совпадением
любой из них.
"""

from __future__ import annotations

from itertools import product

# Для каждой буквы — варианты латинского написания. Первый вариант
# соответствует загранпаспортной схеме, которой пользуется деканат.
LETTERS: dict[str, tuple[str, ...]] = {
    "а": ("a",), "б": ("b",), "в": ("v",), "г": ("g",), "д": ("d",),
    "е": ("e", "ye"), "ё": ("e", "yo"), "ж": ("zh",), "з": ("z",),
    "и": ("i",), "й": ("i", "y"), "к": ("k",), "л": ("l",), "м": ("m",),
    "н": ("n",), "о": ("o",), "п": ("p",), "р": ("r",), "с": ("s",),
    "т": ("t",), "у": ("u",), "ф": ("f",), "х": ("kh", "h"), "ц": ("ts", "c"),
    "ч": ("ch",), "ш": ("sh",), "щ": ("shch", "sch"), "ъ": ("", "ie"),
    "ы": ("y",), "ь": ("",), "э": ("e",), "ю": ("iu", "yu", "ju"),
    "я": ("ia", "ya", "ja"),
}

# Окончания, которые схемы передают по-разному: «-ский» → skii/sky/skiy.
ENDINGS: dict[str, tuple[str, ...]] = {
    "ий": ("ii", "y", "iy", "i"),
    "ый": ("yi", "y", "yy"),
    "ая": ("aia", "aya", "aja"),
    "ья": ("ia", "ya", "ia"),
}

MAX_VARIANTS = 48


def is_cyrillic(text: str) -> bool:
    return any("а" <= char <= "я" or char in "ёЁ" for char in text.lower())


def to_latin(word: str) -> list[str]:
    """Все правдоподобные латинские написания слова, лучший вариант первым."""
    lowered = word.strip().lower()
    if not lowered:
        return []
    if not is_cyrillic(lowered):
        return [lowered]

    stem, tails = lowered, ("",)
    for ending, options in ENDINGS.items():
        if lowered.endswith(ending) and len(lowered) > len(ending):
            stem, tails = lowered[: -len(ending)], options
            break

    per_letter = [LETTERS.get(char, (char,)) for char in stem]

    # Ограничиваем перебор: у длинной фамилии вариантов слишком много,
    # а нужен только разумный набор вокруг паспортной схемы.
    budget = MAX_VARIANTS // max(1, len(tails))
    trimmed: list[tuple[str, ...]] = []
    total = 1
    for options in per_letter:
        if total * len(options) > budget:
            trimmed.append((options[0],))
        else:
            trimmed.append(options)
            total *= len(options)

    variants: list[str] = []
    seen: set[str] = set()
    for letters in product(*trimmed):
        base = "".join(letters)
        for tail in tails:
            candidate = base + tail
            if candidate not in seen:
                seen.add(candidate)
                variants.append(candidate)
    return variants
