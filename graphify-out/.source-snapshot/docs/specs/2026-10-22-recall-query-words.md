# Preserve query words in semantic review

The tokenizer's suffix normalization is useful for deterministic retrieval but
can turn real words into misleading model inputs: pants becomes pant, spectacles
becomes spectacle and sunglasses becomes sunglasse. Keep the normalized overlap
test, then use the actual case-folded query words for every missing concept in
the existing local referent check and native output enum.

Preserve the existing prompt, complete concept coverage, exact report spans,
same_meaning and compatible relation gates. Do not change literal ranking,
semantic thresholds, candidate count, generation budget, deadline, provider or
source eligibility. Keep the six-word and 100-character concept bounds; multiple
distinct surface forms may now conservatively exceed that bound and abstain.

The isolated-word and definition protocols remain rejected experiments. Their
wrong object matches do not justify relaxing the conservative production gate.
This increment addresses a narrower input defect, not general synonym recall.

Acceptance: the real model sees original words instead of lossy stems; it must
repeat exactly those words in its grounded output. Old stem-only responses
cannot be accepted. Compare a frozen targeted set against the unmodified build,
retain mismatch regressions including escalator/lift, van/lorry and lantern/torch,
and run the existing recall and full regressions. Report coverage losses,
unavailable inference and any remaining missed synonyms explicitly.
