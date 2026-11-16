# -*- coding: utf-8 -*-
"""Euronext (Paris / Amsterdam) stock profiles and news-search keywords.

Single source of truth for the short display name and the sector-specific
search keywords of Euronext symbols (Yahoo Finance ``.PA`` / ``.AS``).

- ``get_euronext_stock_name`` feeds ``DataFetcherManager.get_stock_name`` so
  reports and search queries use the short commercial name ("LVMH") instead
  of the long legal name returned by Yahoo.
- ``build_euronext_search_dimensions`` / ``build_euronext_news_query`` feed
  ``SearchService`` so Euronext symbols are searched with French (or English)
  financial vocabulary instead of the A-share Chinese templates.

Symbols that are not listed here still get the generic French templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.services.market_symbol_utils import is_fr_suffix_symbol


@dataclass(frozen=True)
class EuronextStockProfile:
    """Search profile for one Euronext symbol."""

    name: str                 # short display / search name
    sector_keywords: str      # business drivers worth following
    risk_keywords: str = ""   # company-specific risk vocabulary
    kind: str = "stock"       # "stock" or "etf"
    lang: str = "fr"          # language of the search templates: "fr" or "en"
    search_name: str = ""     # disambiguated name for queries (defaults to name)

    @property
    def query_name(self) -> str:
        return self.search_name or self.name


EURONEXT_STOCK_PROFILES: Dict[str, EuronextStockProfile] = {
    "DCAM.PA": EuronextStockProfile(
        name="Amundi PEA Monde MSCI World ETF",
        search_name="MSCI World",
        sector_keywords="actions mondiales Wall Street technologie Fed taux dollar euro",
        risk_keywords="valorisation correction récession",
        kind="etf",
    ),
    "ASML.AS": EuronextStockProfile(
        name="ASML",
        sector_keywords="EUV lithography semiconductor equipment order bookings TSMC AI chip demand",
        risk_keywords="China export restrictions tariffs order cuts",
        lang="en",
    ),
    "BNP.PA": EuronextStockProfile(
        name="BNP Paribas",
        sector_keywords="banque taux BCE marge nette d'intérêts ratio CET1 rachat d'actions dividende",
        risk_keywords="coût du risque amende litige dette souveraine France",
    ),
    "AIR.PA": EuronextStockProfile(
        name="Airbus",
        sector_keywords="livraisons A320 A350 carnet de commandes cadences de production défense spatial",
        risk_keywords="chaîne d'approvisionnement moteurs retards droits de douane",
    ),
    "EDEN.PA": EuronextStockProfile(
        name="Edenred",
        sector_keywords="titres-restaurant avantages aux salariés mobilité professionnelle Brésil Italie",
        risk_keywords="réglementation plafonnement des commissions enquête concurrence",
    ),
    "ENGI.PA": EuronextStockProfile(
        name="Engie",
        sector_keywords="prix du gaz électricité renouvelables réseaux nucléaire Belgique dividende",
        risk_keywords="régulation taxe prix de l'énergie météo",
    ),
    "ENX.PA": EuronextStockProfile(
        name="Euronext",
        search_name="Euronext NV",
        sector_keywords="volumes de transactions introductions en bourse compensation acquisition Bourse d'Athènes",
        risk_keywords="baisse des volumes concurrence régulation",
    ),
    "MC.PA": EuronextStockProfile(
        name="LVMH",
        sector_keywords="luxe Louis Vuitton Dior mode maroquinerie demande Chine États-Unis vins et spiritueux",
        risk_keywords="ralentissement du luxe droits de douane taux de change",
    ),
    "ORA.PA": EuronextStockProfile(
        name="Orange",
        search_name="Orange SA télécoms",
        sector_keywords="fibre 5G MasOrange Afrique Moyen-Orient dividende consolidation télécoms SFR",
        risk_keywords="concurrence prix régulation Arcep",
    ),
    "OVH.PA": EuronextStockProfile(
        name="OVHcloud",
        sector_keywords="cloud souverain IA datacenters croissance du chiffre d'affaires marge EBITDA",
        risk_keywords="endettement concurrence hyperscalers prix de l'électricité",
    ),
    "SAF.PA": EuronextStockProfile(
        name="Safran",
        sector_keywords="moteurs LEAP CFM services après-vente aéronautique défense livraisons",
        risk_keywords="chaîne d'approvisionnement droits de douane retards",
    ),
    "SAN.PA": EuronextStockProfile(
        name="Sanofi",
        sector_keywords="Dupixent pipeline essais cliniques vaccins acquisition biotech",
        risk_keywords="FDA échec essai clinique prix des médicaments États-Unis brevets",
    ),
    "SU.PA": EuronextStockProfile(
        name="Schneider Electric",
        sector_keywords="centres de données électrification gestion de l'énergie automatismes industriels IA",
        risk_keywords="ralentissement de la demande valorisation droits de douane",
    ),
    "SOI.PA": EuronextStockProfile(
        name="Soitec",
        sector_keywords="plaquettes SOI semi-conducteurs smartphones RF-SOI photonique automobile",
        risk_keywords="avertissement sur résultats stocks clients baisse des commandes",
    ),
    "STMPA.PA": EuronextStockProfile(
        name="STMicroelectronics",
        sector_keywords="semi-conducteurs automobile industriel microcontrôleurs carbure de silicium marge brute",
        risk_keywords="stocks baisse de la demande restructuration concurrence chinoise",
    ),
    "HO.PA": EuronextStockProfile(
        name="Thales",
        sector_keywords="défense prises de commandes budget militaire spatial cybersécurité avionique",
        risk_keywords="enquête contrats export géopolitique",
    ),
    "TTE.PA": EuronextStockProfile(
        name="TotalEnergies",
        sector_keywords="pétrole Brent GNL raffinage électricité rachat d'actions dividende",
        risk_keywords="prix du pétrole Mozambique litige climat taxe",
    ),
}


def get_euronext_profile(stock_code: str) -> Optional[EuronextStockProfile]:
    """Return the curated profile for a Euronext symbol, if any."""
    return EURONEXT_STOCK_PROFILES.get((stock_code or "").strip().upper())


def get_euronext_stock_name(stock_code: str) -> Optional[str]:
    """Return the short display name for a curated Euronext symbol."""
    profile = get_euronext_profile(stock_code)
    return profile.name if profile else None


def _resolve(stock_code: str, stock_name: str) -> Optional[EuronextStockProfile]:
    """Return the curated profile, or a generic French one for other Euronext symbols."""
    code = (stock_code or "").strip().upper()
    if not is_fr_suffix_symbol(code):
        return None
    profile = EURONEXT_STOCK_PROFILES.get(code)
    if profile is not None:
        return profile
    name = (stock_name or "").strip() or code
    return EuronextStockProfile(
        name=name,
        sector_keywords="secteur concurrents parts de marché perspectives",
    )


def build_euronext_news_query(stock_code: str, stock_name: str) -> Optional[str]:
    """Main news query for a Euronext symbol; ``None`` for other markets."""
    profile = _resolve(stock_code, stock_name)
    if profile is None:
        return None
    if profile.kind == "etf":
        return f"{profile.query_name} ETF marchés actions actualités"
    if profile.lang == "en":
        return f"{profile.query_name} stock latest news"
    return f"{profile.query_name} action bourse actualités"


def get_euronext_event_types(stock_code: str) -> Optional[List[str]]:
    """Default event keywords for a Euronext symbol; ``None`` for other markets."""
    profile = _resolve(stock_code, "")
    if profile is None:
        return None
    if profile.lang == "en":
        return ["earnings report", "guidance", "quarterly results"]
    return ["résultats trimestriels", "avertissement sur résultats", "dividende"]


def build_euronext_search_dimensions(
    stock_code: str, stock_name: str
) -> Optional[List[Dict[str, Any]]]:
    """Intel search dimensions for a Euronext symbol; ``None`` for other markets.

    Same dimension names and shape as ``SearchService.search_comprehensive_intel``
    so downstream formatting and persistence are unchanged.
    """
    profile = _resolve(stock_code, stock_name)
    if profile is None:
        return None
    name = profile.query_name
    sector = profile.sector_keywords
    risk = profile.risk_keywords

    if profile.kind == "etf":
        queries = {
            "latest_news": f"{name} ETF marchés actions actualités",
            "market_analysis": f"{name} perspectives stratégie allocation actions analystes",
            "risk_check": f"{name} risques {risk}".strip(),
            "earnings": f"{name} performance composition principales positions",
            "industry": f"{name} {sector}",
        }
    elif profile.lang == "en":
        queries = {
            "latest_news": f"{name} stock latest news",
            "market_analysis": f"{name} analyst rating price target",
            "risk_check": f"{name} risk profit warning lawsuit {risk}".strip(),
            "earnings": f"{name} earnings revenue guidance outlook",
            "industry": f"{name} {sector}",
        }
    else:
        queries = {
            "latest_news": f"{name} action bourse actualités",
            "market_analysis": f"{name} analystes recommandation objectif de cours",
            "risk_check": f"{name} risques avertissement sur résultats enquête litige {risk}".strip(),
            "earnings": f"{name} résultats chiffre d'affaires bénéfice prévisions",
            "industry": f"{name} {sector}",
        }

    is_etf = profile.kind == "etf"
    return [
        {
            "name": "latest_news",
            "query": queries["latest_news"],
            "desc": "最新消息",
            "tavily_topic": "news",
            "strict_freshness": True,
        },
        {
            "name": "market_analysis",
            "query": queries["market_analysis"],
            "desc": "机构分析",
            "tavily_topic": None,
            "strict_freshness": False,
        },
        {
            "name": "risk_check",
            "query": queries["risk_check"],
            "desc": "风险排查",
            "tavily_topic": None if is_etf else "news",
            "strict_freshness": not is_etf,
        },
        {
            "name": "earnings",
            "query": queries["earnings"],
            "desc": "业绩预期",
            "tavily_topic": None,
            "strict_freshness": False,
        },
        {
            "name": "industry",
            "query": queries["industry"],
            "desc": "行业分析",
            "tavily_topic": None,
            "strict_freshness": False,
        },
    ]
