"""M2+ — HTTP API + Lambdas (plan §5).

Will hold: HTTP API `ClimbingAgentApi` with a JWT authorizer (prod pool),
the trip CRUD / refresh / job-poll Lambdas, `ComputeTripFn` (async-invoked,
imports `engine/` via a PythonLayerVersion), and `QuotaProbeFn` on a 15-min
EventBridge schedule (M3).
"""
import aws_cdk as cdk
from constructs import Construct

from .auth_stack import AuthStack
from .data_stack import DataStack


class ApiStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *,
                 auth: AuthStack, data: DataStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.auth = auth
        self.data = data
        # M2: apigwv2.HttpApi + JWT authorizer + lambda_.Function per route.
