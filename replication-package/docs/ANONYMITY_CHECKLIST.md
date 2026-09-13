# Double-anonymity checklist

The packaged repository was checked for the following review-time risks:

- no `.git` directory, commit history, remotes, branches, or author emails;
- no author names, affiliations, usernames, hostnames, or identity-bearing repository URL;
- no absolute development or model-checkpoint paths;
- no API keys, environment files, SSH material, or credentials;
- anonymous LaTeX mode and `Anonymous Author(s)` PDF metadata;
- no acknowledgements, grant identifiers, or institution-specific compute description;
- self-citations use ordinary third-person bibliographic style;
- hidden tests are disclosed only inside the private reviewer package;
- third-party licenses are retained separately;
- package integrity is frozen in `MANIFEST.sha256`.

Run `python3 scripts/verify_artifact.py` after any edit. The audit recognizes configured development identities and common secret formats, but automated scanning cannot prove anonymity. Before upload, inspect the hosting account name, repository owner, release metadata, and submission-system filename manually.
