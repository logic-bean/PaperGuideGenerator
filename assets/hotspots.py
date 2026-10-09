# -*- coding: utf-8 -*-
"""Phrase-mining for a conference-guide hotspot list (document frequency).

Drop-in module extracted from the Interspeech 2026 guide builder. Feed it the
list of paper *titles* of one group (a theme, a session, a category ...) and it
returns ``(hot_uni, hot_bi)`` where both are ``[[phrase, n_papers], ...]``.

    from hotspots import hotspots
    # edit LEX_TEXT at the top of this module for the new venue
    uni, combo = hotspots(titles, top_k=12, top_combo=6)

Design rules that this implementation enforces (all were bug fixes):

* the count is the number of **papers** the phrase appears in (DF), never a
  token frequency and never the group size;
* a bare word can never outrank a phrase that contains it
  (`speech recognition` 53 must beat `recognition` 116);
* output must be ``[phrase, n]`` pairs — a list of plain strings silently
  becomes ``n = 1`` at render time;
* the display form is the curated alias (`text speech` -> `text to speech`),
  built longest-first so a phrase never aliases itself away;
* accents are folded (`māori` -> `maori`) and one function word may be skipped
  inside a phrase so hyphenated terms stay whole.
"""
import re, unicodedata
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# 1) Stop words. Keep it tight: over-stopping is what produces fragment chips.
# --------------------------------------------------------------------------
STOP = set('''
the a an of for and with to in on at by from as is are be was were it its this that these those
using use used via based toward towards into over across between among within without under above
below after before each other another during per given than then there here when where what which
who whom whose while both such same many several more less most own out up down off ever never
we our you your they them their he she his her i my not no nor but if so because although
model models learning learn network networks neural deep training train framework frameworks method
methods approach approaches system systems task tasks new novel improved effective robust advanced
proposed present paper results show shows result general specific automatic automated human humans
compared comparison vs versus multi mono cross non un semi self zero shot few not
one two three first second third high low real world large scale small long short fast better best
age know problem solution balancing science technology study work works'''.split())

# --------------------------------------------------------------------------
# 2) Domain lexicon. One line = one concept area; the words are stored both as
#    single terms and as their forward bigrams/trigrams, so curated topics are
#    real multi-word entries. EDIT THIS PER VENUE — it is what makes the chips
#    read like research topics instead of title fragments.
# --------------------------------------------------------------------------
LEX_TEXT = """
speech recognition automatic speech recognition asr
speaker diarization speaker verification speaker adaptation speaker recognition speaker embedding
voice conversion speech enhancement speech separation speech repair speech synthesis
text to speech tts spoken language understanding keyword spotting wake word kws
emotion recognition emotion detection affect detection sentiment analysis stress detection
pain assessment pain detection depression detection parkinson disease parkinsonism
dysarthria dementia alzheimer hearing aid cochlear implant hearing impairment sign language
speech intelligibility speech acquisition language acquisition
multilingual multi language low resource low resource language less resourced under resourced
code switching code mixing zero shot few shot in context
self supervised self supervised learning contrastive learning masked modeling
foundation model large language model speech language model audio language model
machine learning artificial intelligence deep learning neural network
speech translation machine translation speech transformer speech encoder speech decoder
prosody prosody control expressiveness emotional speech timestamp forced alignment alignment
deepfake spoofing anti spoofing voice cloning fake audio generative audio audio generation
hallucination streaming asynchronous causal non causal
data augmentation data annotation annotation quality corpus creation corpus building
data curation data collection data governance data quality data pipeline speech corpus
federated learning differential privacy privacy preserving encryption secure
smart speaker far field in car automotive smart home wearable
child speech elderly school age classroom education literacy
clinical speech clinical assessment telehealth telemedicine remote monitoring
acoustic model acoustic modeling acoustic scene acoustic event audio event event detection
sound event detection music information retrieval audio captioning audio tagging
music generation music transcription
turn taking spoken dialogue task oriented dialogue spoken question answering spoken qa
text normalization punctuation restoration entity extraction relation extraction
intent detection slot filling intent recognition language identification language id
spoken term detection query by example speech retrieval speech search
dysfluency disfluency stuttering filler segmentation voice disorder
speech disorder aphasia stroke hearing loss auditory attention attention
multimodal audio visual visual speech lip reading bimodal
neural codec neural audio codec speech coding bandwidth compression low bitrate
denoising dereverberation reverberation noise robust noise robust speech
microphone array beamforming source separation target speech
explainable interpretable explainability fairness bias trustworthiness
reinforcement learning preference optimization preference learning rlhf
data scarcity data efficiency annotation cost human in the loop
digital health social media self reported self report wellbeing quality of life
pronunciation documentation sociophonetic articulatory phonemic phonetics phonology
indigenous minority language dialect vocal tract articulation perception production
"""

# curated spellings that must survive for readability
ALIAS_EXTRA = {
    'text to speech', 'speech to speech', 'speech to text',
    'text to speech synthesis', 'speech to text translation',
}

NMAX = 3
# one function word may be skipped inside a phrase: 'text-to-speech' would
# otherwise yield the hollow adjacency 'text speech'
FUNC = {'to', 'of', 'and', 'for', 'in', 'with', 'or', 'the', 'a'}


def _deacc(t):
    """Strip accents so 'māori' -> 'maori' (a token must stay whole)."""
    return ''.join(c for c in unicodedata.normalize('NFKD', t)
                   if not unicodedata.combining(c))


def _norm_text(t):
    return re.sub(r"[^a-z0-9]+", " ", _deacc(t.lower())).strip()


def tokens(text):
    return [w for w in _norm_text(text).split() if len(w) >= 3 and w not in STOP]


# --------------------------------------------------------------------------
# 3) Build the curated vocabulary and the alias table
# --------------------------------------------------------------------------
def _build_lexicon():
    terms = set()
    for line in LEX_TEXT.strip().split("\n"):
        ws = [w for w in line.split() if w not in STOP and len(w) >= 3]
        if not ws:
            continue
        terms.update(ws)
        for i in range(len(ws) - 1):
            terms.add(' '.join(ws[i:i + 2]))
            if i + 3 <= len(ws):
                terms.add(' '.join(ws[i:i + 3]))
    terms = {t for t in (_norm_text(x) for x in terms) if t}
    terms |= {_norm_text(x) for x in ALIAS_EXTRA}
    terms = {t for t in terms if t}

    alias = {}
    for t in sorted(terms, key=lambda x: (-len(x.split()), x)):
        key = tuple(w for w in t.split() if w not in FUNC and w not in STOP)
        if key:
            alias.setdefault(key, t)
    return terms, alias


LEX_TERMS, _ALIAS = _build_lexicon()


def _alia(p):
    return _ALIAS.get(tuple(w for w in p.split()
                            if w not in FUNC and w not in STOP), p)


# --------------------------------------------------------------------------
# 4) Mining
# --------------------------------------------------------------------------
def _spans(tk):
    """Emit (start, end) spans of NMAX-long phrases, allowing one function word."""
    for i in range(len(tk)):
        j = i
        skipped = False
        while j < len(tk) and j - i < NMAX:
            if tk[j] in STOP:
                if skipped or tk[j] not in FUNC:
                    break
                skipped = True
                j += 1
                continue
            j += 1
        yield i, j


def _mine(texts):
    """Document frequency per phrase string, plus the token spans it occurs in."""
    df, occ = Counter(), defaultdict(set)
    for ti, t in enumerate(texts):
        tk = tokens(t)
        for i, j in _spans(tk):
            if j - i < 1:
                continue
            g = ' '.join(tk[i:j])
            df[g] += 1
            occ[g].add((ti, i, j - i))
    return df, occ


def _condense(texts):
    """Drop a phrase when a longer phrase dominates it, or ties it in frequency
    at a longer length (ties only condense once the phrase spans >= 2 papers,
    so a single-paper group keeps complete words)."""
    df, occ = _mine(texts)
    keep = {}
    for s, c in df.items():
        supers = set()
        for (ti, i, n) in occ[s]:
            tk = tokens(texts[ti])
            if i + n < len(tk) and not any(w in STOP for w in tk[i:i + n + 1]):
                supers.add(' '.join(tk[i:i + n + 1]))
            if i > 0 and not any(w in STOP for w in tk[i - 1:i + n]):
                supers.add(' '.join(tk[i - 1:i + n]))
        dominated = False
        for q in supers:
            cq = df.get(q, 0)
            if cq > c or (cq == c and len(q.split()) > len(s.split()) and c >= 2):
                dominated = True
                break
        if not dominated:
            keep[s] = c
    return keep


def _lex_df(texts):
    c = Counter()
    for t in texts:
        nt = _norm_text(t)
        c.update({term for term in LEX_TERMS if term in nt})
    return c


def hotspots(texts, top_k=12, top_combo=6):
    """Return (hot_uni, hot_bi) — both lists of ``[phrase, n_papers]``.

    hot_uni : condensed phrases (1..NMAX words) ranked so that full phrases
              come first, then curated terms, then single words.
    hot_bi  : extra multi-word collocations not already shown in hot_uni.
    """
    ldf = _lex_df(texts)
    pool = dict(_condense(texts))
    for k, v in ldf.items():
        # the lexicon counts distinct papers, mining counts occurrences: keep the
        # larger figure so a phrase is never weakened by an overwrite
        pool[k] = max(pool.get(k, 0), v)
    lexset = set(ldf)

    def rank(kv):
        k, v = kv
        return (0 if len(k.split()) >= 2 else 1,
                0 if k in lexset else 1,
                -v, -len(k.split()), k)

    final = sorted(pool.items(), key=rank)
    selected = {}

    def fill(pred, limit):
        for k, v in final:
            if len(selected) >= limit:
                return
            if k in selected or not pred(k, v):
                continue
            # a single word already covered by a listed phrase is noise
            if len(k.split()) == 1 and any(k in shown for shown in selected):
                continue
            selected[k] = v

    # 1) multi-word phrases that involve at least two papers
    fill(lambda k, v: len(k.split()) >= 2 and v >= 2, top_k)

    # 2) curated topic terms — meaningful even for a one-paper group
    def _fresh_lexicon(k, v):
        if v >= 2:
            return k in lexset
        return (k in lexset and len(k.split()) >= 2) or (k in lexset
                and len(k.split()) == 1 and v == 1
                and not any(len(shown.split()) >= 2 for shown in selected)
                and not any(k in shown for shown in selected))
    fill(_fresh_lexicon, min(top_k, len(selected) + 3))

    # 3) recurring single-word keywords not already part of a listed phrase
    def _fresh_unigram(k, v):
        if len(k.split()) != 1 or v < 2 or k in lexset:
            return False
        return not any(k in shown for shown in selected)
    fill(_fresh_unigram, min(top_k, len(selected) + 4))

    # 4) last resort: the single most frequent keyword
    fill(lambda k, v: len(k.split()) == 1, len(selected) + 1)

    # the alias is what gets shown, so de-duplicate on the alias as well
    uni, seen = [], set()
    for k, v in sorted(selected.items(), key=rank):
        a = _alia(k)
        if a in seen:
            continue
        seen.add(a)
        uni.append([a, v])
    combo, seen = [], set(seen)
    for k, v in final:
        if len(k.split()) < 2 or v < 2:
            continue
        a = _alia(k)
        if a in seen:
            continue
        seen.add(a)
        combo.append([a, v])
        if len(combo) >= top_combo:
            break
    return uni, combo


if __name__ == '__main__':
    import sys
    titles = sys.argv[1:] or [
        'Text-to-speech synthesis with text speech translation',
        'Speech recognition for low resource languages',
        'Speaker diarization meets emotion recognition',
    ]
    u, c = hotspots(titles)
    print('uni  :', u)
    print('combo:', c)
