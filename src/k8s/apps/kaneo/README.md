# Kaneo

Kaneo runs at https://projects.sgf.dev with Zitadel OIDC. The deployment pins Kaneo 2.23.2, the version tested by [`glitchedmob/kaneo` v0.1.0](https://github.com/glitchedmob/terraform-provider-kaneo/releases/tag/v0.1.0).

## Authentication

The Terraform provider signs in through `/api/auth/sign-in/email` and uses the returned session token. It does not support Zitadel sign-in, API keys, or interactive MFA.

`DISABLE_LOGIN_FORM=false` enables password sign-in at the API as well as the login form. This setting applies to every password-enabled account, not just the automation account. Zitadel auto-login remains enabled, and password registration, email OTP sign-in, and guest access remain disabled.

## Manual automation account bootstrap

Bootstrap the account outside Terraform. The provider must authenticate before it can manage users.

1. Sign in through Zitadel as an existing Kaneo instance admin.
2. Use that authenticated session and the Better Auth admin API to create a dedicated automation user and set a strong, unique password. Grant the instance `admin` role if Terraform will manage users. Do not add a password to a human's OIDC account for automation. Mark an email verified only after independently verifying it.
3. Store the credentials in the operator's secret manager. Do not commit them or add them to the Kaneo deployment. The provider runs outside the application pods.
4. For existing workspaces, grant the automation account accepted workspace membership with the permissions needed for the managed resources. Instance admin status alone does not grant workspace access. Workspace ownership is appropriate when managing the full workspace and its access.
5. For existing teams, add the automation account to every team Terraform will manage memberships in. Import those relationships into Terraform. For new teams, explicitly manage the operator's team membership before other team memberships, as described in the [provider documentation](https://github.com/glitchedmob/terraform-provider-kaneo/blob/v0.1.0/docs/resources/team_member.md).

Configure the provider endpoint as `https://projects.sgf.dev/api`. Supply `KANEO_USERNAME` and `KANEO_PASSWORD` securely in the environment of the OpenTofu process. Do not print credentials or session tokens in logs. Run OpenTofu only through the repository's Makefile targets.

## Access management and migration

`sgfdevs/infra-iam` is the intended owner of workspace structure and access. This deployment does not create the automation account, workspaces, or memberships.

Import existing users, workspaces, teams, and memberships rather than recreating them. `kaneo_workspace_member` creates an invitation and does not wait for acceptance. A user must accept the invitation before Terraform can create their team memberships; a dependency alone does not satisfy this requirement.

Keep migrated tasks and other working content outside the IAM Terraform state. Review workspace deletion or replacement carefully because it deletes contents.
