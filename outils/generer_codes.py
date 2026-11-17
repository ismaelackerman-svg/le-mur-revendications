"""
ÉTAPE 1 — Générer les codes secrets.

    py -3.12 outils/generer_codes.py --nombre 5000 --reserve 500 --sortie ./sortie

Produit dans le dossier de sortie :
  codes_principaux.txt  → les codes EN CLAIR, à remettre à la personne neutre
  codes_reserve.txt     → idem, pour remplacer un mail perdu
  empreintes.txt        → les empreintes (cachées) : à importer dans le site ET
                          à copier sur la clé USB de référence

⚠️ Les fichiers de codes en clair sont dangereux : avec eux on peut se connecter
à la place d'un étudiant. Génère-les sur un PC propre, juste avant le jour J,
remets-les à la personne neutre, puis SUPPRIME ta copie.
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402


def generer(nombre: int, reserve: int):
    """Renvoie (codes_principaux, codes_reserve, empreintes_triees)."""
    total = nombre + reserve
    codes = set()
    while len(codes) < total:          # le set écarte l'improbable doublon
        codes.add(db.nouveau_code())
    codes = list(codes)                # ordre quelconque : pur hasard de toute façon
    principaux, de_reserve = codes[:nombre], codes[nombre:]
    # Triées : l'ordre du fichier ne dit RIEN sur l'ordre des codes.
    empreintes = sorted(db.empreinte(c) for c in codes)
    return principaux, de_reserve, empreintes


def empreinte_fichier(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def ecrire(sortie: Path, principaux, de_reserve, empreintes) -> Path:
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "codes_principaux.txt").write_text("\n".join(principaux) + "\n", encoding="utf-8")
    (sortie / "codes_reserve.txt").write_text("\n".join(de_reserve) + "\n", encoding="utf-8")
    chemin_emp = sortie / "empreintes.txt"
    chemin_emp.write_text("\n".join(empreintes) + "\n", encoding="utf-8")
    return chemin_emp


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nombre", type=int, required=True, help="nombre d'étudiants")
    p.add_argument("--reserve", type=int, default=0, help="codes de rechange (ex: 10 %%)")
    p.add_argument("--sortie", default="sortie", help="dossier de sortie")
    a = p.parse_args()
    if a.nombre < 1 or a.reserve < 0:
        sys.exit("Les nombres doivent être positifs.")

    principaux, de_reserve, empreintes = generer(a.nombre, a.reserve)
    chemin_emp = ecrire(Path(a.sortie), principaux, de_reserve, empreintes)

    print(f"{len(principaux)} codes principaux + {len(de_reserve)} de réserve générés.")
    print(f"Dossier : {Path(a.sortie).resolve()}")
    print()
    print("EMPREINTE DU FICHIER DE RÉFÉRENCE (à publier AVANT le vote) :")
    print("  " + empreinte_fichier(chemin_emp))
    print()
    print("À FAIRE MAINTENANT :")
    print("  1. Copier empreintes.txt sur la clé USB (+ une 2e copie pour une autre personne).")
    print("  2. Importer empreintes.txt dans le site (outils/importer_empreintes.py).")
    print("  3. Remettre les fichiers codes_*.txt à la personne neutre.")
    print("  4. SUPPRIMER tes copies des fichiers codes_*.txt.")


if __name__ == "__main__":
    main()
