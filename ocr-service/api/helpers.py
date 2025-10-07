import re
# Optional: only import rapidfuzz here if you want to force it to be present
# from rapidfuzz import process, fuzz

CLINICS = {
    # A–Z
    **{f"Clinic {c}": [f"Clinic-{c}", f"{c} Clinic"] for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    # Specialty
    "ENT Clinic": ["ENT", "Ear Nose Throat Clinic", "Otolaryngology Clinic"],
    "Eye Centre": ["Eye Center", "Ophthalmology Clinic"],
    "Orthopaedic Clinic": ["Ortho Clinic", "Orthopedics"],
    "Cocoon Clinic": ["Cocoon", "Cocoon Med", "Cocoon Medical",
                      "Coccon", "Coccoon", "Cocon", "Cocoon Clinlc", "Cocoon Clnic"],  # OCR typos
}

def match(ocr_text: str) -> str | None:
    """Return a single clinic string or None."""
    result = match_single_clinic(ocr_text, CLINICS, thresh_fuzzy=82, min_margin=6)
    return result["location"]  # <-- was result[location]

def match_single_clinic(ocr_text, canonical_to_aliases, **kwargs):
    r = match_best_clinic(ocr_text, canonical_to_aliases, **kwargs)
    loc = r.get("locations", [])
    single = loc[0] if loc else None
    return {
        "location": single,
        "confidence": r.get("confidence"),
        "method": r.get("method"),
        "meta": r.get("meta", {})
    }

def match_best_clinic(ocr_text, canonical_to_aliases, *,
                      dept_words=None, thresh_fuzzy=86, min_margin=6,
                      window_chars=40):
    import re, unicodedata
    try:
        from rapidfuzz import process, fuzz
        _RF = True
    except Exception:
        from difflib import SequenceMatcher
        _RF = False

    def _strip_accents(s: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

    _WS = re.compile(r"\s+")
    _PUNCT = re.compile(r"[^\w\s]")

    def _norm(s: str) -> str:
        s = s.lower()
        s = _strip_accents(s)
        s = s.replace("’", "'")
        s = re.sub(r"\b&\b", " and ", s)
        s = re.sub(r"\bcentre\b", "center", s)
        s = re.sub(r"\bctr\b", " center ", s)
        s = re.sub(r"\bdept\b", " department ", s)
        s = re.sub(r"(?<=[a-z])0(?=[a-z])", "o", s)
        s = re.sub(r"(?<=[a-z])[1l](?=[a-z])", "i", s)
        s = re.sub(r"(?<=[a-z])5(?=[a-z])", "s", s)
        s = _PUNCT.sub(" ", s)
        s = _WS.sub(" ", s).strip()
        return s

    def _acronym(s: str) -> str:
        toks = [t for t in re.split(r"\s+", s) if t and t not in
                {"and","the","of","clinic","center","centre","department"}]
        return "".join(t[0] for t in toks)

    def _auto_variants(name: str):
        base = _norm(name)
        v = {base}
        v.add(base.replace(" and ", " & "))
        v.add(base.replace(" center ", " centre "))
        v.add(base.replace("-", " "))
        v.add(base.replace(" clinic", "").strip())
        v.add(base.replace(" centre ", " center "))
        v.add(base.replace(" department", "").strip())
        return list({_norm(x) for x in v if x})

    def _build_alias_map(c2a: dict):
        alias2canon = {}
        canon_list = list(c2a.keys())
        for canon, aliases in c2a.items():
            pool = set(aliases or []) | {canon}
            pool.add(_acronym(canon))
            for a in list(pool):
                if len(a) >= 3:
                    pool.add(_acronym(a))
            for a in list(pool):
                for v in _auto_variants(a):
                    pool.add(v)
            for a in pool:
                na = _norm(a)
                if na:
                    alias2canon[na] = canon
        return alias2canon, canon_list

    if not dept_words:
        dept_words = ["clinic","centre","center","department","unit","opd","outpatient","specialist","ward"]
    dept_pattern = re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, dept_words)))

    text_norm = _norm(ocr_text)
    alias2canon, canon_list = _build_alias_map(canonical_to_aliases)

    # Stage A: alias
    word_bounded = {}
    for alias in alias2canon.keys():
        if alias:
            word_bounded[alias] = re.compile(r"(?:^|[^a-z0-9])(%s)(?:[^a-z0-9]|$)" % re.escape(alias))

    best_alias, best_alias_pos = None, None
    for alias, pat in word_bounded.items():
        m = pat.search(text_norm)
        if m:
            start, end = m.span(1)
            if (best_alias is None or
                len(alias) > len(best_alias) or
                (len(alias) == len(best_alias) and start < best_alias_pos[0])):
                best_alias = alias
                best_alias_pos = (start, end)

    if best_alias is not None:
        canon = alias2canon[best_alias]
        s, e = best_alias_pos
        left = max(0, s - window_chars)
        right = min(len(text_norm), e + window_chars)
        near_dept = bool(dept_pattern.search(text_norm[left:right]))
        conf = 0.99 if near_dept else 0.97
        return {"locations": [canon], "confidence": conf, "method": "alias",
                "meta": {"alias": best_alias, "near_dept": near_dept}}

    # Stage B: fuzzy
    canon_norms = [_norm(c) for c in canon_list]
    denorm = {cn: c for cn, c in zip(canon_norms, canon_list)}

    if _RF:
        res = process.extract(text_norm, canon_norms, scorer=fuzz.token_set_ratio, limit=3)
        def _dept_bonus_for(name_norm: str) -> int:
            tokens = [t for t in re.split(r"\s+", name_norm) if t and t not in
                      {"clinic","center","centre","and","of","the","department"}]
            hit_near = False
            for t in tokens:
                for m in re.finditer(r"\b%s\b" % re.escape(t), text_norm):
                    s, e = m.span()
                    left = max(0, s - window_chars)
                    right = min(len(text_norm), e + window_chars)
                    if dept_pattern.search(text_norm[left:right]):
                        hit_near = True
                        break
                if hit_near: break
            return 5 if hit_near else (2 if dept_pattern.search(text_norm) else 0)

        if not res:
            return {"locations": [], "confidence": None, "method": None, "meta": {}}

        best_norm, s1, _ = res[0]
        second_norm, s2, _ = res[1] if len(res) > 1 else (None, 0, None)

        a1 = min(100, int(s1) + _dept_bonus_for(best_norm))
        a2 = min(100, int(s2) + (_dept_bonus_for(second_norm) if second_norm else 0))

        if a1 >= thresh_fuzzy and (a1 - a2) >= min_margin:
            return {"locations": [denorm.get(best_norm, best_norm)],
                    "confidence": round(a1/100.0, 2), "method": "fuzzy",
                    "meta": {"raw": int(s1)}}
        return {"locations": [], "confidence": None, "method": None,
                "meta": {"top1": denorm.get(best_norm, best_norm), "scores": [int(s1), int(s2)]}}
    else:
        def score(a,b):
            return int(100*SequenceMatcher(None, a, b).ratio())
        scored = sorted(((cn, score(text_norm, cn)) for cn in canon_norms), key=lambda x: -x[1])
        if not scored: return {"locations": [], "confidence": None, "method": None, "meta": {}}
        best_norm, s1 = scored[0]
        a1 = min(100, s1 + (5 if dept_pattern.search(text_norm) else 0))
        if a1 >= thresh_fuzzy:
            return {"locations": [denorm.get(best_norm, best_norm)],
                    "confidence": round(a1/100.0, 2), "method": "fuzzy", "meta": {"raw": s1}}
        return {"locations": [], "confidence": None, "method": None, "meta": {"raw": s1}}

def extract_clinic_locations(text: str) -> list[str]:
    """Optional regex scraper (not used by matcher)."""
    pattern = re.compile(r"\b(([A-Za-z ]+? Clinic)|(Clinic [A-Za-z ]+))\b", re.I)
    seen, out = set(), []
    for tup in pattern.findall(text):
        clinic = (tup[0] or "").strip().title()
        if clinic and clinic not in seen:
            seen.add(clinic); out.append(clinic)
    return out

