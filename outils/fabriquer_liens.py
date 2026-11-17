"""
Fabrique les liens complets à coller dans le groupe (utile pour un ESSAI avec
quelques codes ; pour 5000 étudiants on passe par envoyer_mails.py).

    py -3.12 outils/fabriquer_liens.py --url https://mon-adresse.trycloudflare.com --codes sortie/codes_principaux.txt

⚠️ Un lien posté dans un groupe est lisible par TOUT le groupe : n'importe qui peut
s'en servir. C'est acceptable pour un essai, pas pour le vrai scrutin.
"""
import argparse
from pathlib import Path


def liens(url: str, codes) -> list[str]:
    return [f"{url.rstrip('/')}/entrer?code={c}" for c in codes]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True)
    p.add_argument("--codes", required=True)
    a = p.parse_args()
    codes = [l.strip() for l in Path(a.codes).read_text(encoding="utf-8").splitlines() if l.strip()]
    for i, lien in enumerate(liens(a.url, codes), 1):
        print(f"{i}. {lien}")


if __name__ == "__main__":
    main()
