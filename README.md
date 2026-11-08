# Wallet API QA Suite

A fintech QA practice project: a small wallet and payment API (transfers, merchant fees, refunds, settlement) backed by a SQLite ledger, with a PyTest suite that tests it through the API and checks the database directly.

The API exists so it can be tested. The value is in the tests.

## What the tests cover
| Area | Examples |
|---|---|
| API positive cases | transfer updates both balances, merchant payment deducts the 1.85% fee |
| API negative and edge cases | zero, negative, 3-decimal, non-numeric and over-limit amounts; 0.01 and exact-balance boundaries; unknown wallet; same-wallet transfer; missing fields; malformed JSON; missing or wrong API key |
| Payment reliability | duplicate request with the same Idempotency-Key charges once; key reused with a different amount returns 409; 5 concurrent "double taps" charge once; concurrent spends never overdraw |
| Refunds | full amount returned and fee reversed; double refund rejected; settled payment cannot be refunded |
| Database validation (SQL) | every transaction's ledger lines sum to zero; wallet balances match ledger history; total money conserved; failed transfers leave no rows; no negative balances; fee rounding to the paisa |
| Settlement and reconciliation | settlement excludes refunded payments, net = gross - fees, matches the merchant balance, never settles twice |

## Run
```bash
pip install -r requirements.txt
pytest                 # all 32 tests
pytest -m api          # API tests
pytest -m db           # SQL data validation
pytest -m integration  # end-to-end settlement flows
pytest --cov=wallet --cov-report=term-missing
```

## API
The OpenAPI (Swagger) spec is in `docs/openapi.yaml`. Paste it into editor.swagger.io to browse it, or import it into Postman to get a ready-made collection.

## CI
GitHub Actions runs the API, database and integration test groups on every push and pull request and uploads a JUnit report.
