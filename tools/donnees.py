"""
Chargement et normalisation des données financières de MIZAN AI.

Trois tableaux sont attendus :
- ventes.csv            : ventes encaissées au comptant
- depenses.csv          : dépenses de l'entreprise
- factures_clients.csv  : ventes à crédit (factures clients)

Le module accepte aussi des fichiers Excel. Toutes les erreurs sont
formulées en français, avec le numéro de ligne quand c'est possible.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

DEVISE = "MAD"


class ErreurDonnees(ValueError):
    """Erreur lisible par l'utilisateur lors de l'import des données."""


@dataclass
class JeuDonnees:
    """Données d'une entreprise, déjà normalisées."""

    entreprise: str
    ville: str
    type_entreprise: str
    date_reference: date
    solde_tresorerie_mad: float | None
    ventes: pd.DataFrame
    depenses: pd.DataFrame
    factures: pd.DataFrame
    devise: str = DEVISE
    hypotheses: dict[str, Any] = field(default_factory=dict)
    fictif: bool = False
    avertissement: str = ""
    source: str = ""
    alertes_import: list[str] = field(default_factory=list)

    def periode_couverte(self) -> tuple[date | None, date | None]:
        """Retourne la première et la dernière date présentes dans les données."""
        dates: list[pd.Timestamp] = []
        for df, colonne in (
            (self.ventes, "date"),
            (self.depenses, "date"),
            (self.factures, "date_emission"),
        ):
            if not df.empty and colonne in df:
                dates.extend(pd.to_datetime(df[colonne]).dropna().tolist())
        if not dates:
            return None, None
        return min(dates).date(), max(dates).date()


# ---------------------------------------------------------------------------
# Utilitaires de nettoyage
# ---------------------------------------------------------------------------

def _nom_colonne(colonne: Any) -> str:
    """Transforme « Montant (MAD) » en « montant_mad »."""
    texte = unicodedata.normalize("NFKD", str(colonne))
    texte = texte.encode("ascii", "ignore").decode("ascii").lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", texte).strip("_")


# Alias acceptés pour faciliter l'import de fichiers déjà existants.
_ALIAS: dict[str, dict[str, str]] = {
    "ventes": {
        "date": "date",
        "date_vente": "date",
        "date_de_vente": "date",
        "client": "client",
        "categorie": "categorie",
        "category": "categorie",
        "produit": "categorie",
        "quantite": "quantite",
        "qte": "quantite",
        "prix_unitaire_mad": "prix_unitaire_mad",
        "prix_unitaire": "prix_unitaire_mad",
        "cout_unitaire_mad": "cout_unitaire_mad",
        "cout_unitaire": "cout_unitaire_mad",
        "montant_mad": "montant_mad",
        "montant": "montant_mad",
        "total": "montant_mad",
        "ca": "montant_mad",
        "cout_mad": "cout_mad",
        "cout": "cout_mad",
        "cout_achat": "cout_mad",
        "cout_achats": "cout_mad",
    },
    "depenses": {
        "date": "date",
        "date_depense": "date",
        "categorie": "categorie",
        "category": "categorie",
        "libelle": "libelle",
        "description": "libelle",
        "montant_mad": "montant_mad",
        "montant": "montant_mad",
        "total": "montant_mad",
    },
    "factures": {
        "facture_id": "facture_id",
        "id_facture": "facture_id",
        "numero_facture": "facture_id",
        "num_facture": "facture_id",
        "client": "client",
        "categorie": "categorie",
        "category": "categorie",
        "date_emission": "date_emission",
        "date_facture": "date_emission",
        "date_echeance": "date_echeance",
        "echeance": "date_echeance",
        "montant_mad": "montant_mad",
        "montant": "montant_mad",
        "total": "montant_mad",
        "montant_paye_mad": "montant_paye_mad",
        "montant_paye": "montant_paye_mad",
        "paye": "montant_paye_mad",
        "cout_mad": "cout_mad",
        "cout": "cout_mad",
        "cout_achat": "cout_mad",
        "date_paiement": "date_paiement",
        "date_reglement": "date_paiement",
    },
}


def _renommer_colonnes(df: pd.DataFrame, type_tableau: str) -> pd.DataFrame:
    """Nettoie et renomme les colonnes selon les alias connus."""
    df = df.copy()
    df.columns = [_nom_colonne(c) for c in df.columns]
    correspondance = _ALIAS[type_tableau]
    gardees: dict[str, str] = {}
    for colonne in df.columns:
        cible = correspondance.get(colonne)
        if cible and cible not in gardees:
            gardees[colonne] = cible
    return df[list(gardees)].rename(columns=gardees)


def _en_nombre(valeur: Any) -> float:
    """Convertit « 1 234,50 MAD » en 1234.5. Retourne NaN si impossible."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return float("nan")
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).strip()
    if not texte:
        return float("nan")
    texte = texte.replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    texte = re.sub(r"(?i)(mad|dhs?|dirhams?|dh)", "", texte)
    texte = re.sub(r"[^0-9,.\-]", "", texte)
    if texte in {"", "-", ".", ","}:
        return float("nan")
    if "," in texte and "." in texte:
        if texte.rfind(",") > texte.rfind("."):
            texte = texte.replace(".", "").replace(",", ".")
        else:
            texte = texte.replace(",", "")
    elif "," in texte:
        texte = texte.replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        return float("nan")


def _controler_nombres(
    serie: pd.Series,
    nom: str,
    *,
    obligatoire: bool = True,
    defaut: float | None = None,
) -> pd.Series:
    valeurs = serie.map(_en_nombre).astype(float)
    if defaut is not None:
        valeurs = valeurs.fillna(defaut)
    manquants = valeurs.isna()
    if obligatoire and manquants.any():
        lignes = (valeurs.index[manquants] + 2).tolist()[:5]
        raise ErreurDonnees(
            f"Colonne « {nom} » : {int(manquants.sum())} valeur(s) manquante(s) "
            f"ou non numérique(s) (ligne(s) {', '.join(map(str, lignes))})."
        )
    return valeurs


def _controler_dates(
    serie: pd.Series,
    nom: str,
    *,
    obligatoire: bool = True,
) -> pd.Series:
    valeurs = pd.to_datetime(serie, errors="coerce", format="mixed", dayfirst=True)
    manquants = valeurs.isna()
    if obligatoire and manquants.any():
        lignes = (valeurs.index[manquants] + 2).tolist()[:5]
        raise ErreurDonnees(
            f"Colonne « {nom} » : {int(manquants.sum())} date(s) illisible(s) "
            f"(ligne(s) {', '.join(map(str, lignes))}). "
            "Format attendu : AAAA-MM-JJ ou JJ/MM/AAAA."
        )
    return valeurs.dt.normalize()


def _verifier_colonnes(df: pd.DataFrame, requises: set[str], type_tableau: str) -> None:
    manquantes = sorted(requises - set(df.columns))
    if manquantes:
        libelles = ", ".join(f"« {c} »" for c in manquantes)
        raise ErreurDonnees(
            f"Le fichier {type_tableau} doit contenir la ou les colonnes {libelles}. "
            "Téléchargez le modèle CSV depuis l'application pour voir le format attendu."
        )


# ---------------------------------------------------------------------------
# Normalisation par tableau
# ---------------------------------------------------------------------------

def normaliser_ventes(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise les ventes au comptant.

    Colonnes minimales : date, categorie, montant_mad.
    Le coût d'achat est facultatif ; s'il manque, la marge ne sera pas calculée.
    """
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["date", "client", "categorie", "quantite", "montant_mad", "cout_mad"]
        )
    df = _renommer_colonnes(df, "ventes").reset_index(drop=True)
    _verifier_colonnes(df, {"date", "categorie", "montant_mad"}, "des ventes")

    resultat = pd.DataFrame(index=df.index)
    resultat["date"] = _controler_dates(df["date"], "date")
    resultat["client"] = (
        df["client"].fillna("Clients de passage").astype(str).str.strip()
        if "client" in df
        else "Clients de passage"
    )
    resultat["client"] = resultat["client"].replace({"": "Clients de passage", "nan": "Clients de passage"})
    resultat["categorie"] = df["categorie"].fillna("Non classé").astype(str).str.strip()
    resultat["quantite"] = (
        _controler_nombres(df["quantite"], "quantite", obligatoire=False, defaut=1.0)
        if "quantite" in df
        else 1.0
    )
    resultat["montant_mad"] = _controler_nombres(df["montant_mad"], "montant_mad")

    # Coût : priorité au coût total, sinon quantité × coût unitaire.
    cout = pd.Series(float("nan"), index=df.index, dtype=float)
    if "cout_mad" in df:
        cout = _controler_nombres(df["cout_mad"], "cout_mad", obligatoire=False)
    if "cout_unitaire_mad" in df:
        cout_unitaire = _controler_nombres(
            df["cout_unitaire_mad"], "cout_unitaire_mad", obligatoire=False
        )
        cout = cout.where(cout.notna(), cout_unitaire * resultat["quantite"])
    resultat["cout_mad"] = cout

    if (resultat["montant_mad"] < 0).any():
        raise ErreurDonnees("Les montants des ventes ne peuvent pas être négatifs.")
    resultat = resultat.dropna(subset=["date"])
    return resultat.sort_values("date").reset_index(drop=True)


def normaliser_depenses(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise les dépenses. Colonnes minimales : date, categorie, libelle, montant_mad."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "categorie", "libelle", "montant_mad"])
    df = _renommer_colonnes(df, "depenses").reset_index(drop=True)
    _verifier_colonnes(df, {"date", "categorie", "libelle", "montant_mad"}, "des dépenses")

    resultat = pd.DataFrame(index=df.index)
    resultat["date"] = _controler_dates(df["date"], "date")
    resultat["categorie"] = df["categorie"].fillna("Non classé").astype(str).str.strip()
    resultat["libelle"] = df["libelle"].fillna("Sans libellé").astype(str).str.strip()
    resultat["montant_mad"] = _controler_nombres(df["montant_mad"], "montant_mad")
    if (resultat["montant_mad"] < 0).any():
        raise ErreurDonnees("Les montants des dépenses ne peuvent pas être négatifs.")
    resultat = resultat.dropna(subset=["date"])
    return resultat.sort_values("date").reset_index(drop=True)


def normaliser_factures(df: pd.DataFrame, alertes: list[str] | None = None) -> pd.DataFrame:
    """Normalise les factures clients.

    Colonnes minimales : facture_id, client, date_emission, date_echeance, montant_mad.
    « montant_paye_mad » manquant est interprété comme 0 (facture impayée).
    """
    alertes = alertes if alertes is not None else []
    colonnes = [
        "facture_id",
        "client",
        "categorie",
        "date_emission",
        "date_echeance",
        "montant_mad",
        "montant_paye_mad",
        "cout_mad",
        "date_paiement",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=colonnes)

    df = _renommer_colonnes(df, "factures").reset_index(drop=True)
    _verifier_colonnes(
        df,
        {"facture_id", "client", "date_emission", "date_echeance", "montant_mad"},
        "des factures clients",
    )

    resultat = pd.DataFrame(index=df.index)
    resultat["facture_id"] = df["facture_id"].astype(str).str.strip()
    if (resultat["facture_id"] == "").any() or resultat["facture_id"].duplicated().any():
        raise ErreurDonnees("Chaque facture doit avoir un identifiant unique (colonne « facture_id »).")
    resultat["client"] = df["client"].fillna("Client non renseigné").astype(str).str.strip()
    resultat["categorie"] = (
        df["categorie"].fillna("Non classé").astype(str).str.strip()
        if "categorie" in df
        else "Non classé"
    )
    resultat["date_emission"] = _controler_dates(df["date_emission"], "date_emission")
    resultat["date_echeance"] = _controler_dates(df["date_echeance"], "date_echeance")
    resultat["montant_mad"] = _controler_nombres(df["montant_mad"], "montant_mad")

    if "montant_paye_mad" in df:
        paye = _controler_nombres(df["montant_paye_mad"], "montant_paye_mad", obligatoire=False)
        if paye.isna().any():
            alertes.append(
                f"{int(paye.isna().sum())} facture(s) sans montant payé : elles sont considérées comme impayées."
            )
        resultat["montant_paye_mad"] = paye.fillna(0.0).clip(lower=0.0)
    else:
        resultat["montant_paye_mad"] = 0.0
        alertes.append("Aucune colonne « montant_paye_mad » : toutes les factures sont considérées comme impayées.")

    resultat["cout_mad"] = (
        _controler_nombres(df["cout_mad"], "cout_mad", obligatoire=False)
        if "cout_mad" in df
        else float("nan")
    )
    resultat["date_paiement"] = (
        _controler_dates(df["date_paiement"], "date_paiement", obligatoire=False)
        if "date_paiement" in df
        else pd.NaT
    )

    if (resultat["montant_mad"] < 0).any():
        raise ErreurDonnees("Les montants des factures ne peuvent pas être négatifs.")
    depassements = resultat["montant_paye_mad"] > resultat["montant_mad"] + 0.01
    if depassements.any():
        lignes = (resultat.index[depassements] + 2).tolist()[:5]
        raise ErreurDonnees(
            "Le montant payé dépasse le montant de la facture "
            f"(ligne(s) {', '.join(map(str, lignes))})."
        )

    invalides = resultat["date_echeance"] < resultat["date_emission"]
    if invalides.any():
        alertes.append(
            f"{int(invalides.sum())} facture(s) ont une échéance antérieure à leur date d'émission."
        )

    resultat = resultat.dropna(subset=["date_emission", "date_echeance"])
    return resultat.sort_values("date_emission").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Lecture de fichiers
# ---------------------------------------------------------------------------

def lire_tableau(source: Any, feuille: str | int | None = None) -> pd.DataFrame:
    """Lit un CSV (virgule, point-virgule ou tabulation) ou un Excel."""
    if isinstance(source, pd.DataFrame):
        return source.copy()

    nom = ""
    if isinstance(source, (str, Path)):
        chemin = Path(source)
        nom = chemin.name
        suffixe = chemin.suffix.lower()
        if suffixe not in {".xlsx", ".xlsm", ".xls", ".csv", ".txt", ""}:
            raise ErreurDonnees(f"Format non pris en charge : {suffixe}. Utilisez un fichier CSV ou Excel.")
        if not chemin.exists():
            raise ErreurDonnees(f"Fichier introuvable : {chemin}")
    else:
        nom = getattr(source, "name", "fichier")
        suffixe = Path(nom).suffix.lower()

    try:
        if suffixe in {".xlsx", ".xlsm", ".xls"}:
            return pd.read_excel(source, sheet_name=feuille if feuille is not None else 0)
        if suffixe in {".csv", ".txt", ""}:
            return pd.read_csv(source, sep=None, engine="python", encoding="utf-8-sig")
        raise ErreurDonnees(f"Format non pris en charge : {suffixe}. Utilisez un fichier CSV ou Excel.")
    except ErreurDonnees:
        raise
    except Exception as exc:  # pandas renvoie des erreurs très techniques
        raise ErreurDonnees(f"Impossible de lire « {nom} ». Vérifiez qu'il s'agit bien d'un CSV ou Excel valide.") from exc


def _trouver_fichier(dossier: Path, prefixes: tuple[str, ...]) -> Path | None:
    for prefixe in prefixes:
        for extension in (".csv", ".xlsx"):
            candidat = dossier / f"{prefixe}{extension}"
            if candidat.exists():
                return candidat
    return None


def charger_jeu_dossier(dossier: str | Path) -> JeuDonnees:
    """Charge un jeu de données complet depuis un dossier.

    Le dossier doit contenir ventes.csv, depenses.csv, factures_clients.csv
    et parametres.json (nom, date de référence, solde de trésorerie).
    """
    dossier = Path(dossier)
    if not dossier.exists():
        raise ErreurDonnees(f"Dossier de données introuvable : {dossier}")

    chemin_params = dossier / "parametres.json"
    if not chemin_params.exists():
        raise ErreurDonnees(f"Fichier « parametres.json » manquant dans {dossier}.")
    try:
        params = json.loads(chemin_params.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ErreurDonnees(f"« parametres.json » est invalide : {exc}") from exc

    if "date_reference" not in params:
        raise ErreurDonnees("« parametres.json » doit contenir « date_reference ».")
    try:
        date_reference = pd.Timestamp(params["date_reference"]).date()
    except Exception as exc:
        raise ErreurDonnees("« date_reference » doit être une date, par exemple 2026-10-19.") from exc

    solde = params.get("solde_tresorerie_initial_mad")
    if solde is not None:
        try:
            solde = float(solde)
        except (TypeError, ValueError) as exc:
            raise ErreurDonnees("« solde_tresorerie_initial_mad » doit être un nombre.") from exc

    chemins = {
        "ventes": _trouver_fichier(dossier, ("ventes",)),
        "depenses": _trouver_fichier(dossier, ("depenses", "dépenses")),
        "factures": _trouver_fichier(dossier, ("factures_clients", "factures")),
    }
    manquants = [nom for nom, chemin in chemins.items() if chemin is None]
    if manquants:
        raise ErreurDonnees(
            "Fichier(s) manquant(s) dans le dossier : "
            + ", ".join(manquants)
            + ". Attendu : ventes.csv, depenses.csv, factures_clients.csv."
        )

    alertes: list[str] = []
    ventes = normaliser_ventes(lire_tableau(chemins["ventes"]))
    depenses = normaliser_depenses(lire_tableau(chemins["depenses"]))
    factures = normaliser_factures(lire_tableau(chemins["factures"]), alertes)

    return JeuDonnees(
        entreprise=str(params.get("entreprise", dossier.name)),
        ville=str(params.get("ville", "")),
        type_entreprise=str(params.get("type_entreprise", "")),
        date_reference=date_reference,
        solde_tresorerie_mad=solde,
        ventes=ventes,
        depenses=depenses,
        factures=factures,
        devise=str(params.get("devise", DEVISE)),
        hypotheses=dict(params.get("hypotheses", {})),
        fictif=bool(params.get("fictif", False)),
        avertissement=str(params.get("avertissement", "")),
        source=str(dossier),
        alertes_import=alertes,
    )


def construire_jeu(
    *,
    ventes: Any,
    depenses: Any,
    factures: Any,
    entreprise: str,
    date_reference: date,
    solde_tresorerie_mad: float | None,
    ville: str = "",
    type_entreprise: str = "",
    hypotheses: dict[str, Any] | None = None,
    source: str = "Import utilisateur",
) -> JeuDonnees:
    """Construit un jeu de données à partir de trois tableaux (chemins ou DataFrames)."""
    alertes: list[str] = []
    jeu = JeuDonnees(
        entreprise=entreprise.strip() or "Mon entreprise",
        ville=ville,
        type_entreprise=type_entreprise,
        date_reference=pd.Timestamp(date_reference).date(),
        solde_tresorerie_mad=solde_tresorerie_mad,
        ventes=normaliser_ventes(lire_tableau(ventes)),
        depenses=normaliser_depenses(lire_tableau(depenses)),
        factures=normaliser_factures(lire_tableau(factures), alertes),
        hypotheses=dict(hypotheses or {}),
        source=source,
        alertes_import=alertes,
    )
    if jeu.ventes.empty and jeu.factures.empty and jeu.depenses.empty:
        raise ErreurDonnees("Les fichiers importés ne contiennent aucune ligne exploitable.")
    return jeu


# ---------------------------------------------------------------------------
# Modèles de fichiers pour l'utilisateur
# ---------------------------------------------------------------------------

def modeles_import() -> dict[str, bytes]:
    """Retourne trois modèles CSV prêts à télécharger depuis l'application."""
    modeles = {
        "ventes.csv": (
            "date,client,categorie,quantite,prix_unitaire_mad,cout_unitaire_mad,montant_mad\n"
            "2026-09-01,Clients de passage,Alimentation,10,12.50,9.00,125.00\n"
        ),
        "depenses.csv": (
            "date,categorie,libelle,montant_mad\n"
            "2026-09-01,Loyer,Loyer du local,4500.00\n"
        ),
        "factures_clients.csv": (
            "facture_id,client,categorie,date_emission,date_echeance,montant_mad,"
            "montant_paye_mad,cout_mad,date_paiement\n"
            "F-001,Client exemple,Alimentation,2026-09-01,2026-10-01,2500.00,0.00,1900.00,\n"
        ),
    }
    return {nom: contenu.encode("utf-8-sig") for nom, contenu in modeles.items()}
