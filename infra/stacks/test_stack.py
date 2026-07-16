"""M5 — test-mode isolation (plan §7).

Will hold: separate user pool `climbing-agent-users-test` (seeded users,
USER_PASSWORD_AUTH enabled for Playwright/agent automation), the `/test`
API stage with TEST_MODE=true, and fully separate *Test DynamoDB tables —
structural, IAM-enforced isolation so test runs can never spend real
SerpApi quota or touch prod rows.
"""
import aws_cdk as cdk
from constructs import Construct


class TestStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # M5: test pool + tables + stage go here.
