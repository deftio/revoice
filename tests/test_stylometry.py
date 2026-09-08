from revoice.voicemetric.features import char_ngram_profile, cosine, fingerprint, word_bigram_profile

TEXT = "The quick brown fox jumps over the lazy dog. It was the best of times; it was the worst of times."


def test_fingerprint_basics():
    fp = fingerprint(TEXT)
    assert fp["words"] > 15
    assert fp["sentences"] == 2  # semicolon does not end a sentence
    assert 0 < fp["type_token_ratio"] <= 1
    assert abs(sum(fp["sent_len_hist"]) - 1.0) < 0.01
    assert fp["function_word_freq"]["the"] > 0


def test_ngram_profiles_and_cosine():
    a = char_ngram_profile(TEXT)
    assert cosine(a, a) > 0.999
    b = char_ngram_profile("Impedance matching networks transform antenna loads.")
    assert cosine(a, b) < cosine(a, a)
    wb = word_bigram_profile(TEXT)
    assert "it was" in wb


def test_empty_text_safe():
    fp = fingerprint("")
    assert fp["words"] == 0
