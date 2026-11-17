"""
Cœur du système : tout ce qui touche aux codes, aux empreintes et à la base.

Règle d'or : la base ne contient JAMAIS un code en clair, ni un nom, ni un mail.
Seulement des empreintes (SHA-256) de codes aléatoires.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent

MAX_PROPOSITIONS = 3          # propositions maximum par compte
TEXTE_MIN, TEXTE_MAX = 10, 400
CODE_LONGUEUR_MAX = 100       # un vrai code fait ~43 caractères


def chemin_base() -> str:
    """Lu à chaque appel pour que les tests puissent changer de base."""
    return os.environ.get("VOTE_DB", str(DOSSIER / "vote.db"))


# ---------------------------------------------------------------- codes
def nouveau_code() -> str:
    """Code aléatoire de 256 bits. Rien à voir avec l'étudiant : pur hasard."""
    return secrets.token_urlsafe(32)


def empreinte(code: str) -> str:
    """Version « cachée » du code. À sens unique : on ne remonte pas au code."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def code_plausible(code) -> bool:
    return isinstance(code, str) and 0 < len(code) <= CODE_LONGUEUR_MAX


# ----------------------------------------------------------------- base
@contextmanager
def connexion(chemin: str | None = None):
    conn = sqlite3.connect(chemin or chemin_base(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
-- WITHOUT ROWID : les lignes sont rangées par empreinte, pas par ordre
-- d'insertion. Sinon l'ordre des comptes pourrait trahir l'ordre des mails.
-- Pas de date non plus, pour la même raison.
-- pseudo / mdp sont vides tant que le lien n'a pas servi. Le lien ne marche
-- qu'UNE fois : ensuite l'étudiant se connecte avec le pseudo et le mot de
-- passe qu'il a choisis lui-même (jamais reliés à son nom ni à son mail).
CREATE TABLE IF NOT EXISTS comptes (
    empreinte TEXT PRIMARY KEY,
    active    INTEGER NOT NULL DEFAULT 0,
    pseudo    TEXT,
    mdp       TEXT
) WITHOUT ROWID;
CREATE UNIQUE INDEX IF NOT EXISTS idx_comptes_pseudo ON comptes(pseudo);

CREATE TABLE IF NOT EXISTS sessions (
    jeton  TEXT PRIMARY KEY,
    compte TEXT NOT NULL,
    expire INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS revendications (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    texte    TEXT NOT NULL,
    auteur   TEXT NOT NULL,
    jour     TEXT NOT NULL,
    masquee  INTEGER NOT NULL DEFAULT 0
);

-- La clé primaire (compte, revendication) rend le double vote IMPOSSIBLE.
CREATE TABLE IF NOT EXISTS votes (
    compte        TEXT NOT NULL,
    revendication INTEGER NOT NULL,
    valeur        INTEGER NOT NULL CHECK (valeur IN (-1, 1)),
    PRIMARY KEY (compte, revendication)
) WITHOUT ROWID;
"""


def init_base(chemin: str | None = None) -> None:
    with connexion(chemin) as conn:
        # Anciennes bases (avant les pseudo/mots de passe) : on ajoute les colonnes.
        existe = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='comptes'"
        ).fetchone()
        if existe:
            colonnes = {c["name"] for c in conn.execute("PRAGMA table_info(comptes)")}
            for col in ("pseudo", "mdp"):
                if col not in colonnes:
                    conn.execute(f"ALTER TABLE comptes ADD COLUMN {col} TEXT")
        conn.executescript(SCHEMA)


def importer_empreintes(empreintes, chemin: str | None = None) -> int:
    """Ajoute des empreintes de comptes. Renvoie le nombre réellement ajouté."""
    init_base(chemin)
    ajoutes = 0
    with connexion(chemin) as conn:
        for e in empreintes:
            e = e.strip().lower()
            if len(e) != 64:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO comptes(empreinte, active) VALUES (?, 0)", (e,)
            )
            ajoutes += cur.rowcount
    return ajoutes


# ------------------------------------------------------------ connexion
def compte_depuis_code(code, chemin: str | None = None):
    """Renvoie l'empreinte si le code est valide, sinon None."""
    if not code_plausible(code):
        return None
    h = empreinte(code)
    with connexion(chemin) as conn:
        ligne = conn.execute(
            "SELECT empreinte FROM comptes WHERE empreinte = ?", (h,)
        ).fetchone()
    return ligne["empreinte"] if ligne else None


def marquer_active(h: str, chemin: str | None = None) -> None:
    with connexion(chemin) as conn:
        conn.execute("UPDATE comptes SET active = 1 WHERE empreinte = ?", (h,))


# --------------------------------------------- inscription et connexion
PSEUDO_RE = re.compile(r"^[a-z0-9_.-]{3,24}$")
MDP_MIN, MDP_MAX = 8, 200
SESSION_JOURS = 90


def normaliser_pseudo(pseudo) -> str:
    return (pseudo or "").strip().lower()


def _hacher_mdp(mdp: str, sel: bytes | None = None) -> str:
    """scrypt : volontairement lent, pour qu'on ne puisse pas deviner un mot de passe en masse."""
    sel = sel or os.urandom(16)
    h = hashlib.scrypt(mdp.encode("utf-8"), salt=sel, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${sel.hex()}${h.hex()}"


def _mdp_correct(mdp: str, stocke: str) -> bool:
    try:
        _, sel, h = stocke.split("$")
        candidat = hashlib.scrypt(
            mdp.encode("utf-8"), salt=bytes.fromhex(sel), n=2**14, r=8, p=1, dklen=32
        ).hex()
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(candidat, h)


_FAUX_MDP = _hacher_mdp("mot de passe bidon")   # pour qu'un pseudo inconnu coûte le même temps


def est_inscrit(h: str, chemin: str | None = None) -> bool:
    with connexion(chemin) as conn:
        ligne = conn.execute("SELECT pseudo FROM comptes WHERE empreinte = ?", (h,)).fetchone()
    return bool(ligne and ligne["pseudo"])


def invitation_valide(code, chemin: str | None = None):
    """Empreinte si le code existe ET n'a pas encore servi à créer un compte."""
    h = compte_depuis_code(code, chemin)
    return h if h and not est_inscrit(h, chemin) else None


def inscrire(h: str, pseudo, mdp, chemin: str | None = None) -> None:
    """Crée l'identifiant de connexion. Le lien ne peut servir qu'UNE fois."""
    pseudo = normaliser_pseudo(pseudo)
    if not PSEUDO_RE.match(pseudo):
        raise ErreurVote("Pseudo : 3 à 24 caractères, lettres, chiffres, . _ - uniquement.")
    if not isinstance(mdp, str) or len(mdp) < MDP_MIN:
        raise ErreurVote(f"Mot de passe : {MDP_MIN} caractères minimum.")
    if len(mdp) > MDP_MAX:
        raise ErreurVote("Mot de passe trop long.")
    stocke = _hacher_mdp(mdp)
    try:
        with connexion(chemin) as conn:
            cur = conn.execute(
                "UPDATE comptes SET pseudo = ?, mdp = ?, active = 1 "
                "WHERE empreinte = ? AND pseudo IS NULL",
                (pseudo, stocke, h),
            )
            if cur.rowcount != 1:
                raise ErreurVote("Ce lien a déjà servi à créer un compte. Connecte-toi avec ton pseudo.")
    except sqlite3.IntegrityError:
        raise ErreurVote("Ce pseudo est déjà pris, choisis-en un autre.")


def verifier_connexion(pseudo, mdp, chemin: str | None = None):
    """Empreinte du compte si pseudo + mot de passe sont bons, sinon None."""
    pseudo = normaliser_pseudo(pseudo)
    mdp = mdp if isinstance(mdp, str) and len(mdp) <= MDP_MAX else ""
    with connexion(chemin) as conn:
        ligne = conn.execute(
            "SELECT empreinte, mdp FROM comptes WHERE pseudo = ?", (pseudo,)
        ).fetchone()
    stocke = ligne["mdp"] if ligne else _FAUX_MDP
    bon = _mdp_correct(mdp, stocke)
    return ligne["empreinte"] if (ligne and bon) else None


def creer_session(h: str, chemin: str | None = None) -> str:
    jeton = secrets.token_urlsafe(32)
    with connexion(chemin) as conn:
        conn.execute("DELETE FROM sessions WHERE expire < ?", (int(time.time()),))
        conn.execute(
            "INSERT INTO sessions(jeton, compte, expire) VALUES (?, ?, ?)",
            (empreinte(jeton), h, int(time.time()) + SESSION_JOURS * 86400),
        )
    return jeton


def compte_depuis_session(jeton, chemin: str | None = None):
    if not code_plausible(jeton):
        return None
    with connexion(chemin) as conn:
        ligne = conn.execute(
            "SELECT compte FROM sessions WHERE jeton = ? AND expire >= ?",
            (empreinte(jeton), int(time.time())),
        ).fetchone()
    return ligne["compte"] if ligne else None


def supprimer_session(jeton, chemin: str | None = None) -> None:
    if code_plausible(jeton):
        with connexion(chemin) as conn:
            conn.execute("DELETE FROM sessions WHERE jeton = ?", (empreinte(jeton),))


# ------------------------------------------------------- revendications
class ErreurVote(ValueError):
    """Erreur affichable telle quelle à l'étudiant."""


def ajouter_revendication(h: str, texte: str, chemin: str | None = None) -> int:
    texte = " ".join((texte or "").split())  # espaces/retours à la ligne propres
    if len(texte) < TEXTE_MIN:
        raise ErreurVote(f"La revendication doit faire au moins {TEXTE_MIN} caractères.")
    if len(texte) > TEXTE_MAX:
        raise ErreurVote(f"La revendication ne peut pas dépasser {TEXTE_MAX} caractères.")
    with connexion(chemin) as conn:
        deja = conn.execute(
            "SELECT COUNT(*) AS n FROM revendications WHERE auteur = ?", (h,)
        ).fetchone()["n"]
        if deja >= MAX_PROPOSITIONS:
            raise ErreurVote(
                f"Tu as déjà fait {MAX_PROPOSITIONS} propositions, c'est le maximum."
            )
        cur = conn.execute(
            "INSERT INTO revendications(texte, auteur, jour) VALUES (?, ?, ?)",
            (texte, h, date.today().isoformat()),
        )
        return cur.lastrowid


def propositions_restantes(h: str, chemin: str | None = None) -> int:
    with connexion(chemin) as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM revendications WHERE auteur = ?", (h,)
        ).fetchone()["n"]
    return max(0, MAX_PROPOSITIONS - n)


def voter(h: str, revendication_id: int, valeur: int, chemin: str | None = None) -> None:
    """valeur : 1 (pour), -1 (contre), 0 (retirer mon vote). Un revote REMPLACE."""
    if valeur not in (-1, 0, 1):
        raise ErreurVote("Vote invalide.")
    with connexion(chemin) as conn:
        existe = conn.execute(
            "SELECT 1 FROM revendications WHERE id = ? AND masquee = 0",
            (revendication_id,),
        ).fetchone()
        if not existe:
            raise ErreurVote("Cette revendication n'existe pas.")
        if valeur == 0:
            conn.execute(
                "DELETE FROM votes WHERE compte = ? AND revendication = ?",
                (h, revendication_id),
            )
        else:
            conn.execute(
                "INSERT INTO votes(compte, revendication, valeur) VALUES (?, ?, ?) "
                "ON CONFLICT(compte, revendication) DO UPDATE SET valeur = excluded.valeur",
                (h, revendication_id, valeur),
            )


def classement(h: str | None = None, chemin: str | None = None) -> list[dict]:
    """Liste classée par score (pour − contre). On ne renvoie jamais l'auteur."""
    with connexion(chemin) as conn:
        lignes = conn.execute(
            """
            SELECT r.id, r.texte, r.jour, (r.auteur = ?) AS a_moi,
                   COALESCE(SUM(CASE WHEN v.valeur =  1 THEN 1 END), 0) AS pour,
                   COALESCE(SUM(CASE WHEN v.valeur = -1 THEN 1 END), 0) AS contre
            FROM revendications r
            LEFT JOIN votes v ON v.revendication = r.id
            WHERE r.masquee = 0
            GROUP BY r.id
            ORDER BY (pour - contre) DESC, pour DESC, r.id ASC
            """,
            (h or "",),
        ).fetchall()
        mes_votes = {}
        if h:
            for v in conn.execute(
                "SELECT revendication, valeur FROM votes WHERE compte = ?", (h,)
            ):
                mes_votes[v["revendication"]] = v["valeur"]
    return [
        {
            "id": l["id"],
            "texte": l["texte"],
            "jour": l["jour"],
            "pour": l["pour"],
            "contre": l["contre"],
            "score": l["pour"] - l["contre"],
            "mon_vote": mes_votes.get(l["id"], 0),
            "a_moi": bool(l["a_moi"]),
        }
        for l in lignes
    ]


# ------------------------------------------------------------ modération
def masquer(revendication_id: int, masquee: bool = True, chemin: str | None = None) -> bool:
    with connexion(chemin) as conn:
        cur = conn.execute(
            "UPDATE revendications SET masquee = ? WHERE id = ?",
            (1 if masquee else 0, revendication_id),
        )
        return cur.rowcount > 0
