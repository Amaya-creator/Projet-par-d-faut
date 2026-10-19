"""Petits utilitaires de formatage en français, montants en MAD."""

from __future__ import annotations


def nombre_mad(valeur: float | None, decimales: int = 2) -> str:
    """Formate un nombre à la française : espace pour les milliers, virgule décimale.

    >>> nombre_mad(4705.74)
    '4 705,74'
    >>> nombre_mad(1500)
    '1 500,00'
    """
    if valeur is None:
        return "montant non disponible"
    texte = f"{valeur:,.{decimales}f}"
    return texte.replace(",", "\u202f").replace(".", ",")


def montant_mad(valeur: float | None) -> str:
    """Montant suivi de l'unité, sans décimales inutiles.

    >>> montant_mad(4705.74)
    '4 705,74 MAD'
    >>> montant_mad(1500.0)
    '1 500 MAD'
    """
    if valeur is None:
        return "montant non disponible"
    decimales = 0 if abs(valeur - round(valeur)) < 0.005 else 2
    return f"{nombre_mad(valeur, decimales)} MAD"


def montant_court(valeur: float | None) -> str:
    """Montant arrondi au dirham, pour les cartes de l'interface.

    Évite que les grands montants soient tronqués dans une colonne étroite.

    >>> montant_court(359724.29)
    '359 724 MAD'
    """
    if valeur is None:
        return "—"
    return f"{nombre_mad(valeur, 0)} MAD"


def pourcentage(valeur: float | None, decimales: int = 1) -> str:
    """Pourcentage à la française.

    >>> pourcentage(42.16)
    '42,2 %'
    """
    if valeur is None:
        return "non disponible"
    return f"{valeur:.{decimales}f} %".replace(".", ",")


def mois_francais(valeur: float | None, decimales: int = 1) -> str:
    """Durée en mois.

    >>> mois_francais(1.5)
    '1,5 mois'
    """
    if valeur is None:
        return "non disponible"
    return f"{valeur:.{decimales}f} mois".replace(".", ",")
