"""Owner first names for Sri Lanka leads, from what we already hold.

    python -m pipeline.owner_names            # show what would be filled in
    python -m pipeline.owner_names --apply    # write contact names (empty ones only)

Sources, most trustworthy first:
  profile   the website link is a personal Facebook profile (first.last.123)
  named     the business is named after a person: "Nimal's Place",
            "Villa by Dilan", "Uncle Sunil Homestay", "Kumara & family"
  trade     the business is a first name plus a trade: "Jayantha Salon",
            "Sameera Tours". Often the owner, sometimes a son or daughter.
Airbnb host names are handled by `python -m pipeline.airbnb names`; names from
the Sri Lanka Tourism register by `python -m pipeline.sltda names`.

A name is only taken when it is a known given name (GIVEN below), so
"Mama's Kitchen" and "Stay by the Sea" are left alone. Every name written is
logged in the lead's history with where it came from, to be confirmed on the call.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

GIVEN = set('''
ajith amal amara amila anil anura anuradha anusha aravinda aruna asanka asela ashan asiri athula ayesh
bandara bandula buddhika chamara chamath chamila chaminda chamindu champika chandana chandima chanaka charith chathura chathuranga
dammika damith danushka dasun deshan dhammika dhanushka dilan dileepa dilhan dilip dilshan dilum dinesh dinuka dulaj dumindu dushan dushantha
eranga eresha gamini gayan gayashan gihan hasitha heshan hiran hiruna indika ishan ishara isuru janaka janith jayantha jeewan
kalana kamal kanchana kapila kasun kavinda kavindu kelum kosala kumara kusal lahiru lakmal lakshan lakshitha lalith lasantha
madhura madushan madushanka mahesh mahinda malinda malith manjula manoj milinda milindu nalaka nalin namal nandana navod nayana
nilantha nimal nimesh nipuna niroshan nishantha nuwan pasan pasindu pathum prabath pradeep prasad prasanna priyantha pubudu
rajitha ranga ranjith rasika ravindra ravindu roshan ruchira rukshan ruwan sachith sagara sahan sajith saman samantha sameera sampath sandun
sanjaya sanjeewa sanka saranga sasanka sasindu senaka shakthi shamal shanaka shantha shehan sisira sudath sudesh sugath sujith sumith sunil
supun suranga suresh susantha tharaka tharanga tharindu thilina thushara tharusha udara udaya upul uditha vimukthi viraj wasantha yasas
anoma chamari chandrika dilani dilini dinusha gayani hansika hiruni inoka ishani kumari madhavi malini nadeesha nilmini niluka nilu
nirosha pushpa ranjani rasangi sachini samanthi sanduni shanthi sriyani sumali thilani udeni vindya yamuna
arun bala ganesh gopal jeyakumar karthik kumar kumaran mohan murugan nathan niranjan prabu rajan rajesh rajkumar ramesh ravi
sathees senthil shankar siva sivakumar suthan thilak vijay vimal priya kavitha lakshmi meena
abdul ahamed ahmed akram ameer anas arshad asif azeem fahim faizal farook fazil hamza haniffa hassan hussain ifthikar ilham imran
irfan ismail jameel kamil mohamed mohammed mohideen mubarak nazeer niyas nizam rameez rifkan rilwan rishad riyas rizkan rizwan
safras shafeek shiraz thahir yusuf zahir fathima
anthony antony charles christopher dominic denver eric francis george jerome john joseph jude kevin marcus mark michael nihal
patrick paul peter richard roger roy ryan sam shane stephen tony angelo
'''.split())

_STOP: set = set()  # names that turn out to be noise go here


def _ok(word: str) -> str:
    w = (word or '').strip().lower()
    return w.capitalize() if w in GIVEN and w not in _STOP else ''


_PATTERNS = [
    re.compile(r"^\W*([A-Za-z]{3,14})['’]s\b"),                                    # Nimal's Place
    re.compile(r"\b(?:by|with|[Ww]ith) ([A-Z][a-z]{2,13})\b"),                      # Villa by Dilan, Tours with Dilshan
    re.compile(r"\b(?:Uncle|Aunty|Mr|Mrs|Chef|Captain|Capt|Master)\.? ([A-Z][a-z]{2,13})\b"),
    re.compile(r"\b([A-Z][a-z]{2,13}) (?:&|and) (?:[Ff]amily|[Ss]ons|[Bb]rothers)\b"),
]
# "Jayantha Salon": a first name straight before a trade word. Names that are
# also everyday words, gods or saints are left out, as are temples and schools.
_AMBIGUOUS = set('''
sagara saman samantha kumari lakshmi ganesh murugan siva shanthi amara aruna udaya ravi roy sam mark paul peter
john joseph anthony antony george francis jude bandara kumara kumar priya nilu ranga sisira wasantha kanchana
pushpa malini meena bala gopal mohan vijay shakthi madhura nayana ishara tharaka thushara asiri sanka nipuna
prasanna charles michael stephen richard christopher dominic patrick angelo tony kevin ryan shane eric denver
marcus roger jerome nathan rajan prabu arun
'''.split())
_TRADE = re.compile(
    r"^\W*(?:new |sri |hotel |villa |the )?([A-Za-z]{3,14}) (?:tours?|travels?|stores?|motors?|salon|saloon|tailors?|"
    r"hardware|bakers?|bakery|hotel|villa|guest|home ?stay|inn|rest|resort|cabanas?|restaurant|cafe|studio|"
    r"electricals?|traders?|trade|enterprises?|garage|auto|cabs?|taxi|safari|pharmacy|textiles?|fashion|"
    r"jewell?ers?|communications?|agency|services?|engineering|furniture|book ?shop|grocery|super|mart|video|"
    r"photo|photography|tyres?|battery|cycle|lodge|place|house|kitchen|foods?|catering|transport|lanka|ayurveda|"
    r"spa|beauty|printers?|timber|mills?|farm|rent)\b", re.I)
_NOT_A_BUSINESS = re.compile(r'temple|church|school|college|vidyal|hospital|memorial|kovil|mosque|devalaya|viharaya|'
                             r'road|mawatha|bank|station|stadium|university|institute', re.I)
_PROFILE = re.compile(r'(?:facebook|fb)\.com/([a-z]{3,14})[._]([a-z]{3,16})[._]\d{1,6}/?(?:\?|$)', re.I)


def find(name: str, website: str = '') -> Optional[Tuple[str, str]]:
    """(first name, source) or None."""
    for rx in _PATTERNS:
        m = rx.search(name or '')
        if m and _ok(m.group(1)):
            return _ok(m.group(1)), 'named'
    m = _PROFILE.search(website or '')
    if m and (_ok(m.group(1)) or _ok(m.group(2))):
        return (_ok(m.group(1)) or m.group(1).capitalize()), 'profile'
    m = _TRADE.search(name or '')
    if m and _ok(m.group(1)) and m.group(1).lower() not in _AMBIGUOUS and not _NOT_A_BUSINESS.search(name):
        return _ok(m.group(1)), 'trade'
    return None


SOURCE_NOTE = {
    'profile': 'their website link is a personal Facebook profile',
    'named': 'the business is named after them',
    'trade': 'the business name starts with it (could be a family member)',
}


def run(apply: bool = False, log=print) -> Dict[str, int]:
    from . import db
    from .sri_lanka import _tables
    tbl, ev_tbl = _tables()
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            f"SELECT id, name, website, slug FROM {tbl} WHERE COALESCE(contact_name, '') = ''")]
    found: List[Tuple[str, str, str, str, bool]] = []
    for r in rows:
        hit = find(r['name'], r['website'] or '')
        if hit:
            found.append((hit[0], hit[1], r['id'], r['name'], bool(r['slug'])))
    counts = {'profile': 0, 'named': 0, 'trade': 0, 'with_preview': 0}
    for name, source, _, business, preview in found:
        counts[source] += 1
        counts['with_preview'] += preview
    for name, source, _, business, preview in [f for f in found if f[4]][:40]:
        log(f'  {business[:44]:44} {name:12} ({source})')
    if apply and found:
        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with db.connect() as con:
            con.executemany(f"UPDATE {tbl} SET contact_name = ? WHERE id = ? AND COALESCE(contact_name, '') = ''",
                            [(n, i) for n, _, i, _, _ in found])
            con.executemany(f'INSERT INTO {ev_tbl} (lead_id, at, detail) VALUES (?, ?, ?)',
                            [(i, ts, f'Contact name {n} guessed because {SOURCE_NOTE[s]}. Confirm on the call.')
                             for n, s, i, _, _ in found])
    log(f'{len(found)} names {"saved" if apply else "found (add --apply)"}: {counts}')
    return counts


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    run(ap.parse_args().apply)
