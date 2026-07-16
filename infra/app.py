#!/usr/bin/env python3
"""CDK app for the multi-user trip planner (decision #36).

Four stacks, deployed independently as the milestones land:
  M1 auth  -> ClimbingAgentAuth   (Cognito pool, Google IdP, groups, Hosted UI)
  M2 data  -> ClimbingAgentData   (DynamoDB Trips/Jobs + dashboards S3 bucket)
  M2+ api  -> ClimbingAgentApi    (HTTP API, JWT authorizer, engine/ Lambdas)
  M5 test  -> ClimbingAgentTest   (separate pool/stage/tables — structural isolation)

`cdk synth` must always pass with no AWS credentials (no context lookups).
Deploys are manual: nothing in CI calls `cdk deploy`.
"""
import os

import aws_cdk as cdk

from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.corpus_db_stack import CorpusDbStack
from stacks.data_stack import DataStack
from stacks.test_stack import TestStack

# Region fixed by the plan (§2). The corpus-DB stack looks up the default VPC,
# which needs an account id: taken from CDK_DEFAULT_ACCOUNT (deploys/local
# synth) and answered from the committed cdk.context.json in credential-less
# CI synth.
ACCOUNT = os.environ.get("CDK_DEFAULT_ACCOUNT", "166832185275")
ENV = cdk.Environment(account=ACCOUNT, region="eu-west-2")

app = cdk.App()
auth = AuthStack(app, "ClimbingAgentAuth", env=ENV)
data = DataStack(app, "ClimbingAgentData", env=ENV)
ApiStack(app, "ClimbingAgentApi", env=ENV, auth=auth, data=data)
TestStack(app, "ClimbingAgentTest", env=ENV)
CorpusDbStack(app, "ClimbingAgentCorpusDb", env=ENV)
app.synth()
