# Demo and Consent Instructions

This directory contains templates and guidelines for running demonstrations of the **Face Identification and Blockchain Verification Pipeline**.

## Privacy and Consent Policy

1. **Explicit Consent Required**: Processing face biometric data requires unambiguous consent from the subject.
2. **Data Minimization**: Raw biometric embeddings are kept in-memory only and never persisted or placed on-chain.
3. **Public Record**: Only a cryptographic hash (`SHA-256`) of the canonical evidence manifest is recorded on the blockchain.
4. **Retention Policy**: Intermediate search copies and candidate files are cleaned up according to the configured `RETENTION_HOURS` policy.

## Running with Your Own Consented Image

1. Place your query image in `demo/consented-query.jpg`.
2. Inspect detected faces:
   ```bash
   python -m app.cli inspect-face --input demo/consented-query.jpg
   ```
3. Run the full pipeline in live or mock mode:
   ```bash
   python -m app.cli run --input demo/consented-query.jpg --face-index 0 --consent-confirmed
   ```
