"""Cross-check Sri Lanka leads against the tourism authority's public register.

srilanka.travel (Sri Lanka Tourism) lists every registered stay, travel agent
and licensed guide with a phone number and an email. Guides are listed under
their own name, so a lead whose phone matches a guide gives us the person who
answers that phone. For stays and agents the email often carries a first name.

    python -m pipeline.sltda fetch            # download the three registers
    python -m pipeline.sltda names            # show matches and names found
    python -m pipeline.sltda names --apply    # write contact names (empty ones only)

Matching is by phone number only, so a match is the same business or person.
Every name written is logged in the lead's history, to be confirmed on the call.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .owner_names import GIVEN

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'batches' / 'sri-lanka' / 'sltda'
API = 'https://www.srilanka.travel/api'
REGISTERS = {  # file name: (path, key of the list in the reply)
    'stays': ('/accommodation?sort=featured', 'stays'),
    'agents': ('/travel-agents?sort=name-asc', 'agents'),
    'guides': ('/guides?sort=name-asc', 'guides'),
}
PERSONAL_MAIL = {'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'ymail.com', 'rocketmail.com',
                 'icloud.com', 'live.com', 'yahoo.co.uk', 'sltnet.lk', 'yahoo.co.in', 'msn.com'}


def _get(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch(log=print) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (path, key) in REGISTERS.items():
        rows: List[Dict[str, Any]] = []
        seen = set()
        page = 1
        while True:
            got = _get(f'{API}{path}&page={page}&limit=100').get(key) or []
            fresh = [g for g in got if g.get('id') not in seen]
            if not fresh:
                break
            seen.update(g.get('id') for g in fresh)
            rows += fresh
            page += 1
            time.sleep(0.5)
        (OUT / f'{name}.json').write_text(json.dumps(rows, ensure_ascii=False))
        log(f'{name}: {len(rows)}')


def phones(*values: Optional[str]) -> List[str]:
    """Last nine digits of every full number in the given fields."""
    out = []
    for v in values:
        for run in re.findall(r'\d[\d \-]{7,}\d', v or ''):
            digits = re.sub(r'\D', '', run)
            if digits.startswith('94'):
                digits = digits[2:]
            if len(digits.lstrip('0')) == 9:
                out.append(digits.lstrip('0'))
    return out


_PARTICLES = {'de', 'don', 'mohamed', 'mohammed', 'muhammed', 'mohomed', 'gedara', 'gedera', 'mudiyanselage',
              'arachchige', 'handi', 'dewage', 'karage', 'kankanamge', 'liyanage', 'hewage', 'pathirannehelage'}


def guide_first_name(full: str, business: str = '') -> str:
    """The name a guide goes by, or '' when the register does not make it clear.
    Family names come first in Sinhala naming and last in others, so take, in
    order: a name that is also in the business name ("Lalith" for "Heritage
    guide Lalith"), the first full word after initials ("H.D. SAMANTHA
    PUSHPALAL"), or a known given name."""
    if re.search(r'\d', full or ''):   # an address typed into the name field
        return ''
    words = [w.lower() for w in re.findall(r'[A-Za-z]+', full or '')]
    real = [w for w in words if len(w) >= 3 and w not in _PARTICLES]
    biz = set(re.findall(r'[a-z]{4,}', (business or '').lower()))
    for w in real:
        if w in biz:
            return w.capitalize()
    if (len(real) >= 2 and re.match(r'\s*(?:[A-Za-z]\.\s*)+', full or '')
            and words[words.index(real[0]) + 1] not in _PARTICLES and not real[0].endswith(_SURNAME_END)):
        return real[0].capitalize()
    for w in real:
        if w in GIVEN and w not in ('bandara', 'kumara', 'kumar'):
            return w.capitalize()
    return ''


_BUSINESS = re.compile(r'resort|villa|hotel|guest|stay|inn$|tour|travel|lanka|house|rest|cabana|holiday|info|'
                       r'book|reserv|home|lodge|beach|safari|hostel|bungalow|cottage|view|garden')
_SURNAME_END = ('singhe', 'singha', 'sinha', 'sekara', 'sekera', 'ratne', 'rathne', 'ratna', 'rathna', 'wardena',
                'wardana', 'wardhana', 'weera', 'nayake', 'nayaka', 'tunga', 'thunga', 'pala', 'dasa', 'siri', 'sena',
                'sooriya', 'suriya', 'koon', 'kody')
_BY_LENGTH = sorted(GIVEN, key=len, reverse=True)


def email_first_name(email: str, business: str) -> str:
    """A given name at the start of a personal mailbox name, e.g.
    nimalperera@gmail.com or dilhan.rc@gmail.com. Left alone when the mailbox
    is named after the business or the match could be part of a longer name."""
    local, _, domain = (email or '').strip().lower().partition('@')
    if domain not in PERSONAL_MAIL or _BUSINESS.search(local):
        return ''
    biz = re.sub(r'[^a-z]', '', (business or '').lower())
    tokens = re.findall(r'[a-z]{3,}', local)
    if not tokens:
        return ''
    token = tokens[0]
    if token in GIVEN:
        hit = token
    else:
        hit = next((g for g in _BY_LENGTH if len(g) >= 5 and g != 'priya' and token.startswith(g)), '')
        rest = token[len(hit):]
        if hit and (len(rest) in (1, 4) or rest.startswith(_SURNAME_END)):
            hit = ''
    return hit.capitalize() if hit and hit not in biz else ''


def registered() -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """phone (nine digits) -> (register, entry). Guides win over the others."""
    by_phone: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for name in ('stays', 'agents', 'guides'):
        f = OUT / f'{name}.json'
        for row in json.loads(f.read_text()) if f.exists() else []:
            for p in phones(row.get('telephone'), row.get('mobile'), row.get('contact_number'),
                            row.get('contact_number_2')):
                by_phone[p] = (name, row)
    return by_phone


def names(apply: bool = False, log=print) -> Dict[str, int]:
    from . import db
    from .sri_lanka import _tables
    tbl, ev_tbl = _tables()
    by_phone = registered()
    with db.connect() as con:
        leads = [dict(r) for r in con.execute(
            f"SELECT id, name, phone, slug, contact_name FROM {tbl} WHERE COALESCE(phone, '') <> ''")]
    counts = {'matched': 0, 'matched_with_preview': 0, 'guide': 0, 'email': 0, 'names_with_preview': 0}
    writes: List[Tuple[str, str, str]] = []   # (contact name, lead id, note)
    notes: List[Tuple[str, str]] = []         # (lead id, note) for matches without a name
    for lead in leads:
        hit = next((by_phone[p] for p in phones(lead['phone']) if p in by_phone), None)
        if not hit:
            continue
        kind, row = hit
        counts['matched'] += 1
        counts['matched_with_preview'] += bool(lead['slug'])
        reg = row.get('registration_number') or ''
        email = (row.get('email') or '').strip()
        if kind == 'guides':
            who = f"{row.get('title') or ''} {row.get('name') or ''}".strip().title()
            first, source = guide_first_name(row.get('name') or '', lead['name']), 'guide'
            note = f'Phone matches licensed tour guide {who} ({reg}) on the Sri Lanka Tourism register.'
        else:
            first, source = email_first_name(email, lead['name']), 'email'
            note = (f"Registered with Sri Lanka Tourism as {(row.get('name') or '').title()} ({reg})."
                    + (f' Email on the register: {email}.' if email else ''))
        if first and not (lead['contact_name'] or '').strip():
            counts[source] += 1
            counts['names_with_preview'] += bool(lead['slug'])
            guess = '' if source == 'guide' else ' guessed from that email'
            writes.append((first, lead['id'], f'{note} Contact name {first}{guess}. Confirm on the call.'))
            if lead['slug']:
                log(f"  {lead['name'][:44]:44} {first:14} ({source})")
        else:
            notes.append((lead['id'], note))
    if apply:
        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with db.connect() as con:
            con.executemany(f"UPDATE {tbl} SET contact_name = ? WHERE id = ? AND COALESCE(contact_name, '') = ''",
                            [(n, i) for n, i, _ in writes])
            done = {r['lead_id'] for r in con.execute(
                f"SELECT lead_id FROM {ev_tbl} WHERE detail LIKE '%Sri Lanka Tourism%'")}
            con.executemany(f'INSERT INTO {ev_tbl} (lead_id, at, detail) VALUES (?, ?, ?)',
                            [(i, ts, d) for _, i, d in writes if i not in done]
                            + [(i, ts, d) for i, d in notes if i not in done])
    log(f'{"Saved" if apply else "Found (add --apply)"}: {counts}')
    return counts


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['fetch', 'names'])
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    fetch() if a.command == 'fetch' else names(a.apply)
