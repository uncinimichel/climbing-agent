"""Hosted corpus Postgres (decision #36) — the cloud home for the taxonomies +
climbs DB that decisions #34/#35 made the curation source of truth.

Aurora PostgreSQL Serverless v2 with scale-to-zero: the cheapest way to run
real Postgres in AWS (~£0 idle — storage pennies; ~$0.12/ACU-hour only while
queried; wakes in ~15s). Chosen over RDS t4g.micro (~£13/mo always-on) and
over Neon/Supabase (kept in-account per Michel's call, 16 Jul 2026).

Access model: public endpoint, TLS forced, inbound 5432 restricted to the
CIDR passed as `-c corpusDbAllowedCidr=<ip>/32` (update the SG when the home
IP changes — see infra/README.md). Credentials live in Secrets Manager
(`climbing-agent/corpus-db`); local tooling opts in via DATABASE_URL, and
the Colima DB remains the default for day-to-day curation.
"""
import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct

# 18.3 = the newest Aurora PostgreSQL in eu-west-2 (checked 17 Jul 2026;
# ServerlessV2FeaturesSupport.MinCapacity=0 verified, so scale-to-zero — the
# ~£0-idle property — survives). Major pinned in LOCKSTEP with the local
# Colima postgis:18 DB: keep the two majors matched when upgrading either.
ENGINE = rds.DatabaseClusterEngine.aurora_postgres(
    version=rds.AuroraPostgresEngineVersion.of("18.3", "18"))


class CorpusDbStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        sg = ec2.SecurityGroup(self, "CorpusDbSg", vpc=vpc, allow_all_outbound=False,
                               description="climbing corpus Postgres - curation access only")
        allowed = self.node.try_get_context("corpusDbAllowedCidr")
        if allowed:
            sg.add_ingress_rule(ec2.Peer.ipv4(allowed), ec2.Port.tcp(5432),
                                "curation (home IP)")

        params = rds.ParameterGroup(self, "ForceSsl", engine=ENGINE,
                                    parameters={"rds.force_ssl": "1"})

        self.cluster = rds.DatabaseCluster(
            self, "CorpusDb",
            engine=ENGINE,
            serverless_v2_min_capacity=0,     # scale-to-zero: £0 while idle
            serverless_v2_max_capacity=1,
            writer=rds.ClusterInstance.serverless_v2("writer", publicly_accessible=True),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[sg],
            credentials=rds.Credentials.from_generated_secret(
                "climbing", secret_name="climbing-agent/corpus-db"),
            default_database_name="climbing",
            parameter_group=params,
            storage_encrypted=True,           # sec review 17 Jul: at-rest encryption
            backup=rds.BackupProps(retention=cdk.Duration.days(7)),
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
        )

        cdk.CfnOutput(self, "Endpoint", value=self.cluster.cluster_endpoint.hostname)
        cdk.CfnOutput(self, "SecretArn", value=self.cluster.secret.secret_arn)
        cdk.CfnOutput(self, "SecurityGroupId", value=sg.security_group_id)
