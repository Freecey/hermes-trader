# hermes-trader — déploiement PAPER auto-hébergé (VM Proxmox / homelab)

Faire tourner le bot **en mode PAPER, en continu, ~1 semaine** sur une VM dédiée,
avec Docker Compose. Deux conteneurs partagent une même image et un volume `/data` :

| service | rôle | port |
|---------|------|------|
| `web`   | dashboard FastAPI + API + flux SSE + console operator | `8000` |
| `loop`  | boucle de trading autonome (scan → recherche IA → exécution → DSL) | — |
| `seed`  | one-shot : dépose la config PAPER dans le volume au 1er boot | — |

Tout l'état (livre paper, trackers DSL, mémoire agent, session-log, config) vit
dans le volume nommé `hermes_data` et survit à `docker compose down`.

> **Pourquoi c'est plus propre qu'en local :** dans le conteneur il n'y a **aucune
> variable `ANTHROPIC_*`** héritée d'un harness, donc le montage MiniMax via
> `ANTHROPIC_BASE_URL` marche sans le `env -u ...` qu'on devait faire sur le poste.

---

## 1. Pré-requis sur la VM

- Une VM Linux (Debian/Ubuntu conseillé), 1 vCPU / 1 Go RAM suffisent largement
  (chaque conteneur est plafonné à 512 Mo).
- Docker + plugin compose installés :
  ```bash
  docker --version
  docker compose version
  ```
  S'ils manquent : `curl -fsSL https://get.docker.com | sh` puis
  `sudo usermod -aG docker $USER` (re-login pour appliquer le groupe).
- Accès réseau sortant (api.minimax.io, api.hyperliquid.xyz, flux RSS).

## 2. Récupérer le code sur la VM

```bash
git clone -b feat/llm-providers git@github.com:Freecey/hermes-trader.git
cd hermes-trader
```
> Branche `feat/llm-providers` = celle qui contient le mode paper, les providers
> LLM, la news RSS et tous les correctifs des audits.

## 3. Créer le `.env.local` (secrets — jamais commité ni dans l'image)

À la **racine** du repo (`hermes-trader/.env.local`) :

```ini
HERMES_LLM_PROVIDER=anthropic
ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic
ANTHROPIC_API_KEY=<ta-clé-minimax>
HERMES_LLM_MODEL=MiniMax-M3
HERMES_LLM_THINKING=adaptive
HERMES_LLM_MAX_TOKENS=4096
HERMES_NEWS_PROVIDER=rss
HERMES_OPERATOR_TOKEN=<32-hex — openssl rand -hex 16>
```
> En PAPER, **aucune clé Hyperliquid n'est requise** (l'exécuteur saute la
> vérification de clé privée). Le bot lit les prix marché en lecture seule.

## 4. Lancer

```bash
cd deploy
docker compose up -d --build      # build l'image + sème la config PAPER + démarre
```

Vérifs :
```bash
docker compose ps                 # web (healthy) + loop (up), seed (exited 0)
docker compose logs -f loop       # cycles de scan toutes les ~60 s
```

Dashboard : `http://<ip-de-la-vm>:8000`
Console operator : `http://<ip-de-la-vm>:8000/operator?token=<HERMES_OPERATOR_TOKEN>`

> Le livre démarre **frais à 100 $** (aucun `.paper-state.json` dans le volume au
> 1er boot → initialisé depuis `paper_starting_equity`). 100 $ = le capital réel
> que tu testerais ensuite, pour que le sizing simulé reflète la réalité.
>
> **Sizing à 100 $ :** `equity_fraction_per_trade` est monté à **0,06** (au lieu
> de 0,02) pour que même le plus petit ordre dépasse le **plancher Hyperliquid de
> ~10,5 $**. À 0,02, un ordre ferait 4–12 $ → en réel HL le remonterait à 10,5 $,
> mais le moteur paper le simulerait tel quel (divergence). À 0,06, notionnel
> 12,6–36 $ selon conviction : paper et réel restent alignés. Cap notionnel/trade
> ramené à 50 $ et coupe-circuit perte/jour à −20 $ (20 % du compte).

## 5. Suivi quotidien

```bash
docker compose logs --since 24h loop | tail -50      # activité du jour
curl -s http://localhost:8000/metrics                 # métriques Prometheus
curl -s http://localhost:8000/api/health              # liveness
```
Le session-log persistant : `docker compose exec web tail -f /data/session-log.jsonl`

## 6. Mettre en pause / reprendre sans tout arrêter

- Via la console operator : passer le mode sur **OFF** (la boucle reste vivante,
  n'ouvre plus de position ; les positions existantes restent gérées par le DSL).
- Via Docker : `docker compose stop loop` puis `docker compose start loop`
  (le dashboard reste servi par `web`).

## 7. Mettre à jour le code

```bash
git pull
cd deploy && docker compose up -d --build       # rebuild + rolling restart
```

## 8. Sauvegarde / restauration de l'état

```bash
# Sauvegarder tout le volume
docker run --rm -v hermes_data:/data -v "$PWD":/backup busybox \
  tar czf /backup/hermes_data-backup.tgz -C /data .

# Restaurer (ou injecter l'ancien livre 9 990,30 $) AVANT le 1er up
docker volume create hermes_data
docker run --rm -v hermes_data:/data -v "$PWD":/backup busybox \
  sh -c "cp /backup/.paper-state.json /data/.paper-state.json"
```

## 9. Tout arrêter / nettoyer

```bash
docker compose down            # arrête les conteneurs, GARDE le volume (l'état)
docker compose down -v         # ⚠️ supprime AUSSI le volume (perte de l'état)
```

---

### Notes

- **Le mode démarre en PAPER** grâce au service `seed` (`cp -n`, donc tes
  changements de mode via la console sont préservés aux redémarrages).
- **Fuseau** : le conteneur est en UTC ; le dashboard convertit vers le fuseau du
  navigateur, les timestamps du session-log sont en epoch ms.
- **Exposition réseau** : `8000` est publié sur toutes les interfaces de la VM.
  Sur un LAN homelab c'est OK (les écritures sont protégées par le token
  operator, la lecture du dashboard est ouverte). Pour restreindre à une IP :
  remplacer `"8000:8000"` par `"127.0.0.1:8000:8000"` et passer par un tunnel SSH.
- **Logs bornés** : rotation json-file 10 Mo × 5 par conteneur — pas de risque de
  saturer le disque sur une semaine.
