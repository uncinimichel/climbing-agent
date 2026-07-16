"""M1 — Cognito auth (plan §4).

Will hold: user pool `climbing-agent-users` (email + Google via Hosted UI),
`users`/`admins` groups (users auto-assigned by a Post Confirmation trigger),
app client `climbing-agent-web` (Authorization Code + PKCE, no secret,
callback = the GitHub Pages `app/callback.html` + localhost for dev).

M0 ships this empty so `cdk synth` and the CI job are proven before any
resource exists. The Google IdP needs a Google Cloud OAuth client ID/secret
(manual, Michel's console) — email sign-in can ship first without it.
"""
import aws_cdk as cdk
from constructs import Construct


class AuthStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # M1: cognito.UserPool / UserPoolClient / UserPoolDomain / groups go here.
        self.user_pool = None
        self.web_client = None
