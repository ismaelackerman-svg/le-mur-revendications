"""
ÉTAPE 2 — Mettre les empreintes dans la base du site.

    py -3.12 outils/importer_empreintes.py --empreintes sortie/empreintes.txt

Les codes en clair ne passent jamais par ici : seulement les empreintes.
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--empreintes", required=True)
    p.add_argument("--db", default=None, help="chemin de la base (défaut : vote.db)")
    a = p.parse_args()

    chemin = Path(a.empreintes)
    lignes = chemin.read_text(encoding="utf-8").split()
    ajoutes = db.importer_empreintes(lignes, a.db)
    print(f"{ajoutes} comptes ajoutés ({len(lignes)} lignes lues).")
    print("Empreinte du fichier : " + hashlib.sha256(chemin.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
