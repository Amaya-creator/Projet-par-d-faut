"""
Générateur de données fictives réalistes pour MIZAN AI.

Deux entreprises sont proposées :
- « Épicerie Al Baraka » à Casablanca : commerce de détail, ventes au comptant,
  quelques clients professionnels qui achètent à crédit.
- « Coopérative Tiznit Miel » à Tiznit : coopérative agricole, ventes à crédit
  auprès de revendeurs, saisonnalité marquée.

Toutes les données sont fictives. Les fichiers produits contiennent un fichier
`parametres.json` avec la mention « fictif » et un avertissement, repris dans
l'interface et dans le prompt de l'agent.

Usage :
    python -m data.generer_donnees
    python -m data.generer_donnees --entreprise cooperative --sortie data/cooperative
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

AVERTISSEMENT_FICTIF = (
    "Données entièrement fictives, créées pour tester MIZAN AI. "
    "Elles ne correspondent à aucune entreprise réelle."
)

# Épicerie : produits, prix et coûts moyens observés dans une supérette de quartier.
PRODUITS_EPICERIE = [
    ("Alimentation", "Farine 5 kg", 42.0, 36.0),
    ("Alimentation", "Huile 5 L", 78.0, 69.0),
    ("Alimentation", "Sucre 2 kg", 26.0, 22.0),
    ("Alimentation", "Riz 1 kg", 14.0, 11.5),
    ("Alimentation", "Thé 200 g", 32.0, 26.0),
    ("Boissons", "Eau 1,5 L", 6.0, 4.2),
    ("Boissons", "Soda 1 L", 9.0, 7.0),
    ("Boissons", "Jus 1 L", 12.0, 9.5),
    ("Hygiène", "Savon 250 g", 8.0, 5.8),
    ("Hygiène", "Dentifrice", 18.0, 14.0),
    ("Hygiène", "Détergent 2 kg", 34.0, 28.0),
    ("Frais", "Lait 1 L", 8.5, 7.0),
    ("Frais", "Yaourt 4x125 g", 12.0, 9.8),
    ("Frais", "Beurre 250 g", 24.0, 20.0),
]

# Coopérative : miel, huile d'argan et amandes, avec une forte saisonnalité.
PRODUITS_COOPERATIVE = [
    ("Miel", "Miel de thym 500 g", 145.0, 95.0),
    ("Miel", "Miel d'oranger 500 g", 130.0, 88.0),
    ("Miel", "Miel de jujubier 500 g", 180.0, 120.0),
    ("Huile d'argan", "Huile d'argan alimentaire 250 ml", 165.0, 105.0),
    ("Huile d'argan", "Huile d'argan cosmétique 100 ml", 120.0, 70.0),
    ("Amandes", "Amandes grillées 1 kg", 95.0, 68.0),
]

DEPENSES_EPICERIE = [
    ("Loyer", "Loyer du local commercial", 4500.0),
    ("Électricité", "Facture d'électricité", 620.0),
    ("Eau", "Facture d'eau", 180.0),
    ("Internet", "Abonnement internet et téléphone", 260.0),
    ("Salaires", "Salaire de l'apprenti", 2800.0),
    ("Transport", "Livraison et carburant du scooter", 450.0),
    ("Emballage", "Sacs et emballages", 220.0),
    ("Taxes locales", "Taxe locale annuelle", 1250.0),
    ("Entretien", "Petit entretien du magasin", 350.0),
]

DEPENSES_COOPERATIVE = [
    ("Loyer", "Loyer de l'atelier", 3200.0),
    ("Électricité", "Facture d'électricité de l'atelier", 780.0),
    ("Eau", "Facture d'eau", 150.0),
    ("Internet", "Abonnement internet", 300.0),
    ("Salaires", "Salaire de la responsable qualité", 4200.0),
    ("Transport", "Transport vers les revendeurs", 900.0),
    ("Emballage", "Pots, étiquettes et cartons", 1100.0),
    ("Taxes locales", "Taxe locale annuelle", 1800.0),
    ("Entretien", "Entretien du matériel d'extraction", 600.0),
]


@dataclass
class Profil:
    """Paramètres d'une entreprise fictive."""

    identifiant: str
    entreprise: str
    ville: str
    type_entreprise: str
    date_reference: date
    solde_tresorerie_mad: float
    produits: list[tuple[str, str, float, float]]
    depenses: list[tuple[str, str, float]]
    ventes_journalieres_min: int
    ventes_journalieres_max: int
    part_ventes_a_credit: float
    clients_pro: list[tuple[str, float]]  # (nom, montant moyen d'une facture)
    saisonnalite: dict[int, float]  # multiplicateur par mois (1 = normal)
    nombre_mois: int = 9
    graine: int = 42
    hypotheses: dict[str, Any] | None = None


PROFILS: dict[str, Profil] = {
    "epicerie": Profil(
        identifiant="epicerie",
        entreprise="Épicerie Al Baraka",
        ville="Casablanca",
        type_entreprise="Commerce de détail",
        date_reference=date(2026, 10, 19),
        solde_tresorerie_mad=18500.0,
        produits=PRODUITS_EPICERIE,
        depenses=DEPENSES_EPICERIE,
        ventes_journalieres_min=18,
        ventes_journalieres_max=42,
        part_ventes_a_credit=0.10,
        clients_pro=[
            ("Café Rif", 2800.0),
            ("École Al Fath", 4200.0),
            ("Snack Océan", 1900.0),
            ("Résidence Yasmine", 3400.0),
        ],
        saisonnalite={1: 0.95, 2: 0.92, 3: 1.0, 4: 1.05, 5: 1.08, 6: 1.1, 7: 1.02,
                       8: 1.0, 9: 1.12, 10: 1.05, 11: 1.0, 12: 0.98},
        graine=42,
    ),
    "cooperative": Profil(
        identifiant="cooperative",
        entreprise="Coopérative Tiznit Miel",
        ville="Tiznit",
        type_entreprise="Coopérative agricole",
        date_reference=date(2026, 10, 19),
        solde_tresorerie_mad=6000.0,
        produits=PRODUITS_COOPERATIVE,
        depenses=DEPENSES_COOPERATIVE,
        ventes_journalieres_min=0,
        ventes_journalieres_max=3,
        part_ventes_a_credit=0.72,
        clients_pro=[
            ("Épicerie fine Anfa", 7800.0),
            ("Hôtel Atlas Agadir", 12500.0),
            ("Boutique Souk El Had", 4600.0),
            ("Grossiste Marrakech Médina", 9600.0),
            ("Coopérative voisine", 3200.0),
        ],
        saisonnalite={1: 0.7, 2: 0.75, 3: 1.15, 4: 1.25, 5: 1.3, 6: 0.95, 7: 0.8,
                       8: 0.85, 9: 1.0, 10: 1.1, 11: 1.2, 12: 1.35},
        graine=7,
    ),
}


def _fin_mois(mois: date) -> date:
    return (pd.Timestamp(mois) + pd.offsets.MonthEnd(0)).date()


def _debut_mois(mois: date) -> date:
    return mois.replace(day=1)


def _jours_du_mois(mois: date, date_max: date) -> list[date]:
    """Tous les jours du mois, limités à la date de référence."""
    debut, fin = _debut_mois(mois), _fin_mois(mois)
    fin = min(fin, date_max)
    return [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]


def _mois_historique(reference: date, nombre_mois: int) -> list[date]:
    """Liste des premiers jours de mois, du plus ancien au mois de référence."""
    mois = []
    courant = _debut_mois(reference)
    for _ in range(nombre_mois):
        mois.append(courant)
        courant = (pd.Timestamp(courant) - pd.offsets.MonthBegin(1)).date()
    return list(reversed(mois))


def generer_ventes(profil: Profil, rng: random.Random) -> pd.DataFrame:
    """Ventes au comptant, jour par jour, avec une légère saisonnalité."""
    lignes: list[dict[str, object]] = []
    for mois in _mois_historique(profil.date_reference, profil.nombre_mois):
        facteur = profil.saisonnalite.get(mois.month, 1.0)
        for jour in _jours_du_mois(mois, profil.date_reference):
            # Le dimanche, l'épicerie reste ouverte mais vend moins.
            facteur_jour = 0.7 if jour.weekday() == 6 else 1.0
            nombre_ventes = rng.randint(profil.ventes_journalieres_min, profil.ventes_journalieres_max)
            if profil.identifiant == "cooperative":
                nombre_ventes = max(0, round(nombre_ventes * facteur * facteur_jour))
            for _ in range(nombre_ventes):
                categorie, _produit, prix, cout = rng.choice(profil.produits)
                quantite = rng.choice([1, 1, 1, 2, 2, 3, 4])
                # Variation de prix modérée, comme dans un petit commerce.
                prix_applique = round(prix * rng.uniform(0.97, 1.03), 2)
                cout_applique = round(cout * rng.uniform(0.98, 1.02), 2)
                lignes.append(
                    {
                        "date": jour.isoformat(),
                        "client": "Clients de passage",
                        "categorie": categorie,
                        "quantite": quantite,
                        "prix_unitaire_mad": prix_applique,
                        "cout_unitaire_mad": cout_applique,
                        "montant_mad": round(prix_applique * quantite, 2),
                    }
                )
            # Ventes professionnelles au comptant (petites commandes).
            if profil.identifiant == "epicerie" and rng.random() < 0.18:
                client, montant_moyen = rng.choice(profil.clients_pro)
                montant = round(montant_moyen * rng.uniform(0.15, 0.35), 2)
                categorie, _, _, _ = rng.choice(profil.produits)
                lignes.append(
                    {
                        "date": jour.isoformat(),
                        "client": client,
                        "categorie": categorie,
                        "quantite": 1,
                        "prix_unitaire_mad": montant,
                        "cout_unitaire_mad": round(montant * 0.78, 2),
                        "montant_mad": montant,
                    }
                )
    df = pd.DataFrame(lignes)
    # Tri puis arrondi : le coût total reste cohérent avec le montant.
    df = df.sort_values("date").reset_index(drop=True)
    return df


def generer_factures(profil: Profil, rng: random.Random) -> pd.DataFrame:
    """Factures clients à crédit, avec des retards volontairement réalistes.

    Le scénario est fixé, pas laissé au hasard :
    - le dernier client de la liste est un payeur en difficulté ;
    - une facture ancienne de ce client reste impayée ou partiellement payée,
      ce qui crée une créance à risque exploitable par la démonstration ;
    - les autres clients paient, parfois avec un peu de retard.
    """
    lignes: list[dict[str, object]] = []
    compteur = 1
    mois_liste = _mois_historique(profil.date_reference, profil.nombre_mois)
    client_en_difficulte = profil.clients_pro[-1][0]

    for index, mois in enumerate(mois_liste):
        est_mois_courant = mois == _debut_mois(profil.date_reference)
        nombre_factures = rng.randint(3, 6) if profil.identifiant == "cooperative" else rng.randint(2, 4)
        if est_mois_courant:
            nombre_factures = max(1, nombre_factures // 2)

        for _ in range(nombre_factures):
            client, montant_moyen = rng.choice(profil.clients_pro)
            facteur = profil.saisonnalite.get(mois.month, 1.0)
            montant = round(montant_moyen * facteur * rng.uniform(0.7, 1.3), 2)
            categorie, _, _, _ = rng.choice(profil.produits)

            # Émission répartie dans le mois.
            dernier_jour = _fin_mois(mois) if not est_mois_courant else profil.date_reference
            jours_possibles = max(1, (dernier_jour - mois).days)
            emission = mois + timedelta(days=rng.randint(0, jours_possibles))
            delai_paiement = rng.choice([30, 30, 30, 45, 45, 60])
            echeance = emission + timedelta(days=delai_paiement)
            anciennete = (profil.date_reference - emission).days

            paye = False
            date_paiement: date | None = None
            montant_paye = 0.0

            if client == client_en_difficulte:
                # Ce client accumule les retards : une facture ancienne reste
                # impayée, les autres paient tard ou partiellement.
                if anciennete > 100 and rng.random() < 0.75:
                    montant_paye = 0.0
                elif anciennete > 70 and rng.random() < 0.55:
                    montant_paye = round(montant * rng.choice([0.3, 0.5]), 2)
                elif anciennete > delai_paiement + 10:
                    paye = True
                    date_paiement = echeance + timedelta(days=rng.choice([15, 25, 35, 50]))
            else:
                if anciennete > delai_paiement + 25 and rng.random() < 0.94:
                    paye = True
                    date_paiement = echeance + timedelta(days=rng.choice([0, 2, 5, 8, 12]))
                elif anciennete > delai_paiement and rng.random() < 0.8:
                    paye = True
                    date_paiement = echeance + timedelta(days=rng.randint(0, 20))

            if paye and date_paiement is not None and date_paiement > profil.date_reference:
                paye = False
                date_paiement = None
            if paye:
                montant_paye = montant

            lignes.append(
                {
                    "facture_id": f"F-{compteur:04d}",
                    "client": client,
                    "categorie": categorie,
                    "date_emission": emission.isoformat(),
                    "date_echeance": echeance.isoformat(),
                    "montant_mad": montant,
                    "montant_paye_mad": montant_paye,
                    "cout_mad": round(montant * 0.65, 2),
                    "date_paiement": date_paiement.isoformat() if date_paiement else "",
                }
            )
            compteur += 1

    return pd.DataFrame(lignes).sort_values("date_emission").reset_index(drop=True)


def generer_depenses(
    profil: Profil,
    rng: random.Random,
    ventes: pd.DataFrame,
    factures: pd.DataFrame,
) -> pd.DataFrame:
    """Dépenses mensuelles récurrentes, achats de marchandises et imprévus.

    Les achats de marchandises correspondent au coût des ventes du mois
    (comptant et factures), avec une petite variation de stock. Ils sont
    inclus ici car ce sont de vraies sorties de trésorerie ; le calcul de
    marge les retire pour éviter tout double comptage.
    """
    lignes: list[dict[str, object]] = []
    couts_par_mois: dict[str, float] = {}
    if not ventes.empty:
        dates = pd.to_datetime(ventes["date"])
        couts = ventes.assign(
            cout_total=ventes["cout_unitaire_mad"] * ventes["quantite"],
            mois=dates.dt.to_period("M").astype(str),
        )
        couts_par_mois = couts.groupby("mois")["cout_total"].sum().to_dict()
    if not factures.empty:
        dates = pd.to_datetime(factures["date_emission"])
        couts = factures.assign(mois=dates.dt.to_period("M").astype(str))
        for mois, montant in couts.groupby("mois")["cout_mad"].sum().items():
            couts_par_mois[mois] = couts_par_mois.get(mois, 0.0) + float(montant)

    for mois in _mois_historique(profil.date_reference, profil.nombre_mois):
        est_mois_courant = mois == _debut_mois(profil.date_reference)
        dernier_jour = profil.date_reference if est_mois_courant else _fin_mois(mois)
        for categorie, libelle, montant in profil.depenses:
            # Certaines charges ne tombent pas tous les mois.
            if categorie == "Taxes locales" and mois.month not in {1, 7}:
                continue
            if categorie == "Entretien" and rng.random() < 0.4:
                continue
            jour = min(mois.day + rng.randint(0, 6), dernier_jour.day)
            date_depense = mois.replace(day=max(1, jour))
            variation = rng.uniform(0.95, 1.08)
            lignes.append(
                {
                    "date": date_depense.isoformat(),
                    "categorie": categorie,
                    "libelle": libelle,
                    "montant_mad": round(montant * variation, 2),
                }
            )
        # Achats de marchandises : coût des ventes du mois, ajusté du stock.
        cout_du_mois = couts_par_mois.get(mois.strftime("%Y-%m"), 0.0)
        if cout_du_mois:
            achats = cout_du_mois * rng.uniform(0.92, 1.06)
            lignes.append(
                {
                    "date": min(mois.replace(day=5), dernier_jour).isoformat(),
                    "categorie": "Achats de marchandises",
                    "libelle": "Réassort fournisseur",
                    "montant_mad": round(achats, 2),
                }
            )
        # Imprévu occasionnel.
        if rng.random() < 0.25:
            lignes.append(
                {
                    "date": min(mois.replace(day=18), dernier_jour).isoformat(),
                    "categorie": "Réparation",
                    "libelle": "Réparation imprévue",
                    "montant_mad": round(rng.uniform(300, 1500), 2),
                }
            )
    return pd.DataFrame(lignes).sort_values("date").reset_index(drop=True)


def generer_profil(profil: Profil, dossier: Path) -> dict[str, Path]:
    """Génère les trois CSV et le fichier de paramètres pour un profil."""
    rng = random.Random(profil.graine)
    dossier.mkdir(parents=True, exist_ok=True)

    ventes = generer_ventes(profil, rng)
    factures = generer_factures(profil, rng)
    depenses = generer_depenses(profil, rng, ventes, factures)

    chemins = {
        "ventes": dossier / "ventes.csv",
        "depenses": dossier / "depenses.csv",
        "factures": dossier / "factures_clients.csv",
        "parametres": dossier / "parametres.json",
    }
    # utf-8-sig : Excel ouvre correctement les accents.
    ventes.to_csv(chemins["ventes"], index=False, encoding="utf-8-sig")
    depenses.to_csv(chemins["depenses"], index=False, encoding="utf-8-sig")
    factures.to_csv(chemins["factures"], index=False, encoding="utf-8-sig")

    parametres = {
        "entreprise": profil.entreprise,
        "ville": profil.ville,
        "type_entreprise": profil.type_entreprise,
        "date_reference": profil.date_reference.isoformat(),
        "solde_tresorerie_initial_mad": profil.solde_tresorerie_mad,
        "devise": "MAD",
        "fictif": True,
        "avertissement": AVERTISSEMENT_FICTIF,
        "hypotheses": profil.hypotheses
        or {
            "taux_recouvrement_retard": 0.70,
            "taux_recouvrement_contentieux": 0.30,
            "jours_par_mois": 30,
            "fenetre_historique_jours": 90,
            "historique_minimum_jours": 30,
        },
    }
    chemins["parametres"].write_text(
        json.dumps(parametres, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chemins


def generer_tout(dossier_racine: str | Path = "data") -> dict[str, dict[str, Path]]:
    """Génère les deux jeux de données fictifs."""
    racine = Path(dossier_racine)
    return {
        identifiant: generer_profil(profil, racine / identifiant)
        for identifiant, profil in PROFILS.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère les données fictives de MIZAN AI.")
    parser.add_argument(
        "--entreprise",
        choices=sorted(PROFILS) + ["toutes"],
        default="toutes",
        help="Profil à générer (par défaut : toutes).",
    )
    parser.add_argument("--sortie", default="data", help="Dossier de sortie (par défaut : data).")
    args = parser.parse_args()

    if args.entreprise == "toutes":
        resultats = generer_tout(args.sortie)
    else:
        profil = PROFILS[args.entreprise]
        resultats = {args.entreprise: generer_profil(profil, Path(args.sortie) / args.entreprise)}

    for identifiant, chemins in resultats.items():
        print(f"\n{identifiant} :")
        for chemin in chemins.values():
            taille = chemin.stat().st_size if chemin.exists() else 0
            print(f"  - {chemin} ({taille} octets)")
    print(f"\n{AVERTISSEMENT_FICTIF}")


if __name__ == "__main__":
    main()
