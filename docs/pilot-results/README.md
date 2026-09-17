# Pilot test artifacts

`live.json` is produced only by the real-provider HTTP test. `passed` describes
the AI Service boundary, not the external backend/frontend integration. Business
data is the synthetic 24-month demo corpus, not a customer's production ERP.

Run from ai-service:

```powershell
docker compose -f compose.pilot.yaml build pilot
docker compose -f compose.pilot.yaml run --rm pilot
```

The configured `.env` credentials are passed by Compose, never embedded in images
or artifacts. Offline tests are not pilot acceptance evidence.
