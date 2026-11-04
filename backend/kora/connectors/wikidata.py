"""Wikidata connector: the identity hub.

A Wikidata person item links Open Library, OpenAlex, ORCID, VIAF, ISNI and
Library of Congress identifiers, which lets us merge source identities
deterministically ("hard-id" confidence).
"""

from __future__ import annotations

from typing import Any

from kora.connectors.base import BaseConnector
from kora.models import RawPerson

API = "https://www.wikidata.org/w/api.php"

ID_PROPERTIES = {
    "P648": "openlibrary",
    "P10283": "openalex",
    "P496": "orcid",
    "P214": "viaf",
    "P213": "isni",
    "P244": "loc",
    "P1960": "google_scholar",
}
AFFILIATION_PROPERTIES = ("P69", "P108")  # educated at, employer
HUMAN = "Q5"


def _claim_values(claims: dict[str, Any], prop: str) -> list[Any]:
    out = []
    for c in claims.get(prop, []):
        dv = (c.get("mainsnak") or {}).get("datavalue")
        if dv is not None:
            out.append(dv.get("value"))
    return out


def _year(claims: dict[str, Any], prop: str) -> int | None:
    for v in _claim_values(claims, prop):
        if isinstance(v, dict) and "time" in v:
            try:
                return int(v["time"][1:5])
            except ValueError:
                continue
    return None


class WikidataConnector(BaseConnector):
    name = "wikidata"

    async def search_people(self, query: str) -> list[RawPerson]:
        found = await self.http.get_json(
            API,
            {
                "action": "wbsearchentities",
                "search": query,
                "language": "en",
                "type": "item",
                "limit": 8,
                "format": "json",
            },
        )
        qids = [s["id"] for s in found.get("search", [])]
        if not qids:
            return []
        entities = await self._entities(qids, "labels|aliases|descriptions|claims|sitelinks")

        people: list[tuple[dict[str, Any], list[str]]] = []
        affiliation_qids: set[str] = set()
        for qid in qids:  # keep search relevance order
            e = entities.get(qid) or {}
            claims = e.get("claims") or {}
            instance_of = {v.get("id") for v in _claim_values(claims, "P31") if isinstance(v, dict)}
            if HUMAN not in instance_of:
                continue
            aff = [
                v["id"]
                for p in AFFILIATION_PROPERTIES
                for v in _claim_values(claims, p)
                if isinstance(v, dict) and "id" in v
            ]
            affiliation_qids.update(aff)
            people.append((e, aff))

        labels: dict[str, str] = {}
        if affiliation_qids:
            aff_entities = await self._entities(sorted(affiliation_qids)[:50], "labels")
            labels = {
                q: (e.get("labels") or {}).get("en", {}).get("value", q)
                for q, e in aff_entities.items()
            }

        return [self._person(e, [labels.get(q, q) for q in aff]) for e, aff in people]

    async def _entities(self, qids: list[str], props: str) -> dict[str, Any]:
        data = await self.http.get_json(
            API,
            {
                "action": "wbgetentities",
                "ids": "|".join(qids),
                "props": props,
                "languages": "en",
                "format": "json",
            },
        )
        return data.get("entities", {})

    def _person(self, e: dict[str, Any], affiliations: list[str]) -> RawPerson:
        claims = e.get("claims") or {}
        identifiers: dict[str, list[str]] = {}
        for prop, scheme in ID_PROPERTIES.items():
            vals = [str(v) for v in _claim_values(claims, prop) if isinstance(v, str)]
            if vals:
                identifiers[scheme] = vals
        sitelinks = e.get("sitelinks") or {}
        enwiki = (sitelinks.get("enwiki") or {}).get("title")
        label = (e.get("labels") or {}).get("en", {}).get("value") or e["id"]
        aliases = [a["value"] for a in (e.get("aliases") or {}).get("en", [])]
        return RawPerson(
            source=self.name,
            source_id=e["id"],
            name=label,
            alt_names=aliases,
            description=(e.get("descriptions") or {}).get("en", {}).get("value"),
            birth_year=_year(claims, "P569"),
            death_year=_year(claims, "P570"),
            affiliations=affiliations,
            identifiers=identifiers,
            url=f"https://www.wikidata.org/wiki/{e['id']}",
            popularity=len(sitelinks),
            wikipedia_title=enwiki,
        )
