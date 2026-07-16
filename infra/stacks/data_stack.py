"""M2/M3 — data layer (plan §2).

Will hold (all on-demand, ~£0 at this scale — decision #36 kept DynamoDB+S3
over any hosted Postgres):
  ClimbingAgentTrips        PK USER#<sub>, SK TRIP#<ulid>; GSI ByCreatedAt for /admin/trips
  ClimbingAgentFlightCache  PK ROUTE#<o>-<d>, SK DATES#<out>_<back>; TTL ~20h (shared dedup)
  ClimbingAgentQuota        PK QUOTA#GLOBAL, SK DAY#/MONTH# (atomic spend counters)
  ClimbingAgentJobs         PK JOB#<id>; TTL ~7d
  dashboards S3 bucket      computed payloads >400KB live here, not in items
"""
import aws_cdk as cdk
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # M2: dynamodb.TableV2 x4 + s3.Bucket go here.
        self.trips_table = None
        self.dashboards_bucket = None
