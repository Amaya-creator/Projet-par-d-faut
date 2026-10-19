# MIZAN AI

Copilote financier pour les petites entreprises marocaines (commerçants,
coopératives, microentreprises) qui n'ont pas de compétences comptables.

MIZAN AI lit trois fichiers (ventes, dépenses, factures clients), calcule des
indicateurs, projette la trésorerie sur trois mois et propose 3 à 5 actions
concrètes, chacune justifiée par un chiffre. Un agent conversationnel permet de
poser des questions en français simple.

**Tous les montants sont en MAD (dirhams).** Le prototype ne calcule pas la TVA.

> Les deux jeux de données fournis sont **entièrement fictifs**. Ils servent à
> tester l'outil et ne correspondent à aucune entreprise réelle.

---

## 1. Installation

Prérequis : Python 3.11 ou plus récent.

```bash
# Depuis la racine du projet
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Pour activer le chat avec le vrai modèle :

```bash
# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-..."

# macOS / Linux
export ANTHROPIC_API_KEY="sk-ant-..."
```

Sans clé, l'application fonctionne quand même : les calculs sont réels, mais le
chat utilise un mode hors ligne à base de gabarits. L'interface le signale
clairement.

Variables optionnelles :

| Variable | Effet |
|---|---|
| `ANTHROPIC_API_KEY` | Active le chat avec le modèle |
| `MIZAN_MODEL` | Nom du modèle (défaut : `claude-sonnet-4-5`) |

---

## 2. Lancement

```bash
streamlit run app/streamlit_app.py
```

L'application s'ouvre sur `http://localhost:8501`. Choisissez dans la barre
latérale :

- **Données fictives de démonstration** : l'épicerie ou la coopérative ;
- **Importer mes fichiers** : vos trois fichiers CSV ou Excel.

### Régénérer les données fictives

```bash
python -m data.generer_donnees
```

Les fichiers sont écrits dans `data/epicerie/` et `data/cooperative/`.

### Lancer les tests

```bash
python -m pytest tests -q
```

---

## 3. Structure du projet

```
.
├── app/
│   └── streamlit_app.py        Interface : import, onglets, chat
├── agent/
│   ├── agent.py                Boucle tool use + mode hors ligne
│   ├── outils.py               Schémas JSON des outils et exécution
│   └── prompt.py               Prompt système
├── data/
│   ├── generer_donnees.py      Générateur des deux entreprises fictives
│   ├── epicerie/               CSV + parametres.json
│   └── cooperative/            CSV + parametres.json
├── tools/
│   ├── donnees.py              Import, nettoyage, validation
│   ├── kpi.py                  Ventes, dépenses, marge, évolution
│   ├── creances.py             Impayés, retards, créances à risque
│   ├── prevision_tresorerie.py Projection sur 3 mois
│   ├── recommandations.py      Actions chiffrées et priorisées
│   └── formatage.py            Affichage français des montants
├── tests/                      81 tests unitaires
├── requirements.txt
└── README.md
```

---

## 4. Format des fichiers

Trois fichiers sont nécessaires. Les colonnes sont insensibles à la casse et
acceptent des alias courants (`Montant (MAD)`, `Catégorie`, `Date de vente`…).
Les séparateurs CSV `,` et `;` sont détectés automatiquement. Les montants
peuvent contenir des espaces, des virgules décimales et le suffixe `MAD`.

### `ventes.csv` — ventes au comptant

| Colonne | Obligatoire | Description |
|---|---|---|
| `date` | oui | Date de la vente |
| `categorie` | oui | Famille de produit |
| `montant_mad` | oui | Montant encaissé |
| `client` | non | `Clients de passage` par défaut |
| `quantite` | non | 1 par défaut |
| `cout_unitaire_mad` | non | Coût d'achat unitaire |
| `cout_mad` | non | Coût total (prioritaire sur le coût unitaire) |

Sans coût d'achat, la marge n'est **pas** calculée : l'application l'indique au
lieu d'estimer.

### `depenses.csv`

| Colonne | Obligatoire |
|---|---|
| `date` | oui |
| `categorie` | oui |
| `libelle` | oui |
| `montant_mad` | oui |

La catégorie `Achats de marchandises` est traitée à part : elle compte dans les
sorties de trésorerie, mais pas dans le résultat (le coût est déjà dans la
marge), pour éviter un double comptage.

### `factures_clients.csv`

| Colonne | Obligatoire | Description |
|---|---|---|
| `facture_id` | oui | Identifiant unique |
| `client` | oui | Nom du client |
| `date_emission` | oui | Date de facturation |
| `date_echeance` | oui | Date limite de paiement |
| `montant_mad` | oui | Montant facturé |
| `montant_paye_mad` | non | 0 si absent |
| `date_paiement` | non | Date du règlement |
| `cout_mad` | non | Coût des marchandises vendues |

Des modèles CSV sont téléchargeables depuis la barre latérale de l'application.

### `parametres.json` (dossiers de démonstration)

```json
{
  "entreprise": "Épicerie Al Baraka",
  "ville": "Casablanca",
  "date_reference": "2026-10-19",
  "solde_tresorerie_initial_mad": 18500,
  "devise": "MAD",
  "fictif": true,
  "avertissement": "Données entièrement fictives…",
  "hypotheses": {
    "taux_recouvrement_retard": 0.70,
    "taux_recouvrement_contentieux": 0.30,
    "repartition_recouvrement_retard": [0.5, 0.3, 0.2],
    "jours_par_mois": 30,
    "fenetre_historique_jours": 90,
    "historique_minimum_jours": 30
  }
}
```

---

## 5. Ce que calcule l'outil

### Ventes, dépenses, marge

- **Chiffre d'affaires** = ventes au comptant + factures clients émises.
- **Marge brute** = chiffre d'affaires − coût d'achat des marchandises.
- **Résultat estimé** = marge brute − dépenses d'exploitation.
- Totaux par mois, par catégorie, par client.
- Évolution entre les **deux derniers mois complets** ; le mois en cours est
  affiché mais exclu de la comparaison.

### Créances

- Solde dû = montant facturé − montant payé.
- Retard calculé à la date de référence, classé en tranches (non échue, 1-30,
  31-60, 61-90, plus de 90 jours).
- **Créance à risque** : plus de 60 jours de retard, ou client dont le délai
  moyen de paiement dépasse 30 jours sur ses factures déjà réglées.

### Prévision de trésorerie

Fenêtres de 30 jours, sur trois mois :

- ventes au comptant et dépenses prolongées à partir de la moyenne journalière
  des 90 derniers jours ;
- factures non échues encaissées à leur échéance ;
- factures en retard étalées sur les premiers mois avec un taux de
  recouvrement explicite (70 %, ou 30 % au-delà de 90 jours) ;
- alerte dès que le solde projeté devient négatif.

Les hypothèses sont affichées dans l'interface et renvoyées par l'outil. Ce sont
des **hypothèses de travail**, pas des statistiques observées.

### Recommandations

Moteur déterministe, entre 3 et 5 actions triées par priorité. Chaque action
contient :

- un titre et une action concrète ;
- une justification qui reprend les chiffres calculés ;
- la liste des chiffres utilisés, avec leur montant.

Les seuils (`15 %` de marge, `10 %` de hausse des dépenses, `40 %` de
concentration client…) servent seulement à **classer** les actions. Ce ne sont
pas des moyennes du secteur.

---

## 6. L'agent

Le modèle ne calcule jamais un chiffre. Il dispose de cinq outils :

| Outil | Rôle |
|---|---|
| `analyser_ventes_depenses` | CA, dépenses, marge, évolution, catégories |
| `analyser_creances` | Impayés, retards, créances à risque |
| `prevoir_tresorerie` | Projection sur 1 à 12 mois |
| `generer_recommandations` | 3 à 5 actions chiffrées |
| `resume_donnees` | Période, volume et qualité des données |

La boucle est dans `agent/agent.py` : appel du modèle, exécution des outils
demandés, renvoi des résultats JSON, puis réponse finale. Une erreur d'outil est
renvoyée au modèle sous forme de JSON, pour qu'il l'explique sans inventer.

Le prompt système impose :

- aucun calcul par le modèle ;
- une source chiffrée pour chaque affirmation ;
- un français simple, sans jargon ;
- l'annonce explicite des données manquantes ;
- aucune donnée fictive présentée comme réelle.

---

## 7. Exemples de questions

- « Pourquoi ma trésorerie baisse ? »
- « Quelles factures sont impayées ? »
- « Combien vais-je avoir en trésorerie dans deux mois ? »
- « Quelle est ma marge sur les boissons ? »
- « Que faire pour améliorer ma situation ? »
- « Quelles données as-tu ? »

Exemple de réponse attendue (coopérative fictive) :

> La trésorerie deviendrait négative en décembre 2026, avec un point bas de
> 3 091,15 MAD. Les factures en retard représentent 39 871,72 MAD : leur
> encaissement couvrirait ce déficit.
>
> **Action :** relancer en priorité les 12 factures en retard, en commençant par
> le client qui doit 28 172,42 MAD depuis plus de 60 jours.

---

## 8. Limites connues

- Pas de TVA, pas de paie, pas d'amortissements : le résultat est une
  **estimation de gestion**, pas une comptabilité.
- La prévision suppose que les 90 derniers jours représentent les 90 prochains.
  Une activité saisonnière forte peut fausser la projection.
- Les taux de recouvrement sont des hypothèses modifiables, pas des prévisions
  statistiques.
- Le prototype ne se connecte à aucune banque ni à aucune plateforme de
  facturation.
- Les données importées restent en mémoire de session ; rien n'est stocké sur
  disque par l'application.

---

## 9. Tests

```bash
python -m pytest tests -q
```

Les tests couvrent :

- l'import et la validation des fichiers (`test_donnees.py`) ;
- les KPI, la marge et les évolutions (`test_kpi.py`) ;
- les créances, retards et créances à risque (`test_creances.py`) ;
- la prévision de trésorerie et ses alertes (`test_prevision.py`) ;
- les recommandations et le formatage (`test_recommandations.py`) ;
- la boucle d'agent, avec un faux client Anthropic (`test_agent.py`) ;
- la cohérence des données fictives (`test_donnees_fictives.py`).
