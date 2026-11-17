# Plateforme de revendications étudiantes

Chaque étudiant reçoit **un lien personnel par mail**, valable **une seule fois** : il sert à
créer un **pseudo et un mot de passe** (choisis par l'étudiant, reliés ni à son nom ni à son mail).
Ensuite, il se **connecte** avec ça, chaque semaine, pour proposer des revendications (3 maximum)
et voter **pour ou contre** (un seul vote par revendication, modifiable). Le classement
(pour − contre) décide lesquelles vont en AG.

⚠️ Pseudo et mot de passe ne sont **pas récupérables** (aucun mail n'est conservé pour envoyer un
lien de secours). Un étudiant qui les perd doit recevoir un code de la réserve et recommencer
un compte : d'où l'importance du contrôle du nombre de comptes.

## Comment ça protège l'anonymat, en simple

1. On tire au hasard autant de **codes secrets** que d'étudiants (+ une réserve).
2. Une **personne neutre** envoie un code par mail à chaque étudiant, dans un ordre mélangé,
   puis supprime son fichier. Elle ne voit jamais le site.
3. Le site ne garde que **l'empreinte** de chaque code (version cachée, impossible à remettre
   à l'endroit). Il ne contient **ni nom, ni mail, ni code**. Voler la base ne permet de se
   connecter à la place de personne.
4. Une **clé USB hors ligne** garde la liste de référence des empreintes pour détecter des
   faux comptes ajoutés.

Il n'y a **aucune « clé de hachage »** : la recette (SHA-256) est publique. La sécurité vient du
fait que les codes sont longs et aléatoires.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `app.py` | le site (connexion, propositions, votes) |
| `db.py` | la base et toutes les règles (empreintes, un vote par compte…) |
| `static/` | la page (HTML/CSS/JS) |
| `outils/generer_codes.py` | étape 1 : crée les codes et les empreintes |
| `outils/importer_empreintes.py` | étape 2 : met les empreintes dans le site |
| `outils/envoyer_mails.py` | étape 3 : envoi des liens (par la personne neutre) |
| `outils/verifier.py` | contrôle : base du site = clé USB ? |
| `outils/moderer.py` | masquer une revendication (doublon, insulte) |
| `tests/test_vote.py` | 34 tests automatiques |

## Le jour J, pas à pas

**Avant (équipe technique)**
1. `py -3.12 outils/generer_codes.py --nombre 5000 --reserve 500 --sortie sortie`
   → note l'**empreinte du fichier** affichée et publie-la dans le groupe.
2. Copie `sortie/empreintes.txt` sur la **clé USB** (+ une 2ᵉ copie pour une autre personne).
3. `py -3.12 outils/importer_empreintes.py --empreintes sortie/empreintes.txt`
4. Remets `codes_principaux.txt` et `codes_reserve.txt` à la personne neutre, puis
   **supprime tes copies**.
5. Mets le site en ligne (`LANCER.bat`, derrière HTTPS) avec **les journaux d'accès coupés**.

**Envoi (personne neutre, devant témoin)**
1. Essai à blanc (n'envoie rien, n'affiche aucun code) :
   `py -3.12 outils/envoyer_mails.py --emails etudiants.txt --codes codes_principaux.txt --url https://notre-site.fr --domaine univ-exemple.fr`
2. Envoi réel : ajouter `--envoyer --smtp-hote … --smtp-utilisateur … --expediteur …`
3. Le programme **supprime lui-même le fichier de codes** à la fin.
4. Un mail perdu : renvoyer avec un code de `codes_reserve.txt` (l'ancien ne peut pas être annulé :
   un étudiant pourrait avoir deux comptes, d'où le contrôle ci-dessous).

**Pendant et après (au moins deux personnes, indépendamment)**
`py -3.12 outils/verifier.py --reference F:\empreintes.txt --etudiants 5000`
→ doit répondre « ✅ tout est conforme ». Sinon : faux comptes, comptes supprimés ou liens partagés.

## Lancer en local pour essayer

```
LANCER.bat          (puis ouvrir http://127.0.0.1:8100)
py -3.12 tests/test_vote.py
```
Pour essayer : génère 5 codes (`--nombre 5 --sortie essai`), importe les empreintes, puis ouvre
`http://127.0.0.1:8100/entrer?code=<un code de essai/codes_principaux.txt>` : la page propose de
créer un pseudo et un mot de passe.

**Mettre en ligne (accessible de partout)** : double-clic sur `METTRE-EN-LIGNE.bat` (site + tunnel
Cloudflare, adresse provisoire qui change à chaque lancement). `outils/fabriquer_liens.py` refait
les liens avec la nouvelle adresse.

## Limites à annoncer honnêtement

- Un étudiant peut **donner son lien** à quelqu'un d'autre (on le détecte seulement par le total).
- Un lien de remplacement ne **peut pas annuler** l'ancien (personne ne sait quelle empreinte est la sienne).
- Un même compte reste **reconnaissable d'un vote à l'autre** (anonyme, pas un scrutin secret).
- La personne qui envoie les mails voit un instant le lien adresse ↔ code : d'où la personne neutre,
  le témoin, et la suppression du fichier.
- Lire le code ne prouve pas à lui seul ce qui tourne le jour J (cf. Thompson, *Reflections on
  Trusting Trust*) : d'où les **contrôles extérieurs au code** (clé USB, total des comptes).
- Pour une décision très engageante (ex. blocage), préférer un scrutin vérifiable type Belenios.

## À faire avant la mise en ligne réelle

- HTTPS obligatoire (le cookie passe en `Secure` tout seul derrière HTTPS).
- **Couper les journaux d'accès** du serveur et du proxy : le code est dans l'adresse du lien.
- Héberger sous le nom du **collectif**, avec un deuxième administrateur.
- Sauvegarder la base régulièrement.

## Limites et menaces (dites franchement)

- **Rien ne prouve qu'un clic vient d'un étudiant.** Un lien posté dans un groupe peut être pris par
  n'importe quel membre. L'envoi individuel par mail (personne neutre) limite ce risque, pas le groupe.
- **Cloudflare voit le trafic** (mots de passe compris) : il termine le HTTPS du tunnel.
- **L'hébergeur voit la base** : pseudos et votes par pseudo, jamais un nom ni un mail. Le code ouvert
  montre ce que le site est censé faire, pas ce qui tourne réellement sur la machine : prévoir un
  second administrateur et un hébergement au nom du collectif.
- **Ce n'est pas un scrutin secret** : un pseudo est reconnaissable d'un vote à l'autre.
- Les limites d'essais sont en mémoire (remises à zéro au redémarrage).
- Ce code n'a pas fait l'objet d'un audit externe.
