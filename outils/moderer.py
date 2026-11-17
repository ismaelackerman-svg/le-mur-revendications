"""
MODÉRATION — masquer une revendication (doublon, insulte, hors sujet).

    py -3.12 outils/moderer.py --lister
    py -3.12 outils/moderer.py --masquer 12
    py -3.12 outils/moderer.py --afficher 12      (annuler)

Masquer ne supprime rien : la revendication disparaît du classement mais reste
en base, donc la modération reste vérifiable. À faire à deux personnes.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=None)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--lister", action="store_true")
    g.add_argument("--masquer", type=int)
    g.add_argument("--afficher", type=int)
    a = p.parse_args()

    if a.lister:
        with db.connexion(a.db) as conn:
            for r in conn.execute("SELECT id, texte, masquee FROM revendications ORDER BY id"):
                print(f"{r['id']:>4} {'[MASQUÉE]' if r['masquee'] else '          '} {r['texte']}")
        return
    cible, masquer = (a.masquer, True) if a.masquer else (a.afficher, False)
    ok = db.masquer(cible, masquer, a.db)
    print(("Fait." if ok else "Numéro introuvable."))


if __name__ == "__main__":
    main()
