"""The browser Studio (decision #40 phase B) — everything ~pennies/month:

  CloudFront + private S3 bucket   the static Studio UI (index.html + config.js)
  HTTP API + Cognito JWT           the SAME FastAPI app the local Studio runs,
    + Lambda (Mangum)              in Lambda over the record bucket
  Cognito user pool                Michel + Dan, email+password (users created
                                   post-deploy via CLI; no self-signup)

The record bucket already exists (created outside CDK, deliberately never
managed by a stack so no teardown can touch the data). Photos flow browser↔S3
via presigned URLs — Lambda's 6MB payload cap never sees a crag photo.
Run infra/build_studio_assets.sh before deploying.
"""
import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as authz
from aws_cdk import aws_apigatewayv2_integrations as integ
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as cfo
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_lambda as lam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

RECORD_BUCKET = "climbing-agent-db-backups-166832185275"


class StudioStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        pool = cognito.UserPool(
            self, "Curators",
            user_pool_name="climbing-studio-curators",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(min_length=12),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        client = pool.add_client(
            "StudioWeb",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            id_token_validity=cdk.Duration.hours(12),
            refresh_token_validity=cdk.Duration.days(30),
        )

        # UI: private bucket behind CloudFront (OAC)
        ui_bucket = s3.Bucket(
            self, "Ui",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        dist = cf.Distribution(
            self, "Cdn",
            default_behavior=cf.BehaviorOptions(
                origin=cfo.S3BucketOrigin.with_origin_access_control(ui_bucket),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
        )
        studio_origin = f"https://{dist.domain_name}"

        record = s3.Bucket.from_bucket_name(self, "Record", RECORD_BUCKET)
        fn = lam.Function(
            self, "Api",
            function_name="ClimbingAgentStudioApi",
            runtime=lam.Runtime.PYTHON_3_12,
            architecture=lam.Architecture.X86_64,
            code=lam.Code.from_asset("lambda-build"),
            handler="handler.handler",
            memory_size=1024,
            timeout=cdk.Duration.seconds(30),
            environment={
                "RECORD_BUCKET": RECORD_BUCKET,
                "UPLOAD_DIR": "/tmp/uploads",
                "ALLOWED_ORIGIN": studio_origin,
            },
        )
        record.grant_read_write(fn)

        api = apigwv2.HttpApi(
            self, "Http",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=[studio_origin],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["authorization", "content-type"],
                max_age=cdk.Duration.hours(1),
            ),
        )
        # explicit methods, NOT ANY: an ANY route also matches the CORS
        # preflight OPTIONS, which then dies on the JWT authorizer (401);
        # with no OPTIONS route, API Gateway answers preflights itself
        api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST,
                     apigwv2.HttpMethod.PUT, apigwv2.HttpMethod.DELETE,
                     apigwv2.HttpMethod.PATCH],
            integration=integ.HttpLambdaIntegration("ApiInt", fn),
            authorizer=authz.HttpUserPoolAuthorizer("Jwt", pool, user_pool_clients=[client]),
        )

        s3deploy.BucketDeployment(
            self, "UiDeploy",
            destination_bucket=ui_bucket,
            distribution=dist,               # invalidate on redeploy
            sources=[
                s3deploy.Source.asset("ui-build"),
                s3deploy.Source.data("config.js",
                    f"window.API_BASE='{api.api_endpoint}';"
                    f"window.COGNITO={{region:'eu-west-2',clientId:'{client.user_pool_client_id}'}};"),
            ],
        )

        cdk.CfnOutput(self, "StudioUrl", value=studio_origin)
        cdk.CfnOutput(self, "ApiUrl", value=api.api_endpoint)
        cdk.CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        cdk.CfnOutput(self, "ClientId", value=client.user_pool_client_id)
