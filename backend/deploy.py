"""Deploy the shared layer, the Lambdas and the HTTP API to the Learner Lab.

Usage (from the project root, with the Lab's credentials in ~/.aws/credentials):

    python backend/deploy.py              # deploy everything
    python backend/deploy.py --only auth  # deploy one function (layer is always checked)

Configuration is read from backend/deploy.env (copy deploy.env.example).
Every function runs with the Lab's existing LabRole; nothing in IAM is created.
"""

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
PROJECT = "marketplace"
RUNTIME = "python3.12"
LAYER_NAME = f"{PROJECT}-common"
API_NAME = f"{PROJECT}-api"

# Each function lists its routes and which MySQL users it gets.
# "core"/"secure" is the prefix of the credentials in deploy.env,
# e.g. "AUTH" -> AUTH_CORE_DB_USER / AUTH_CORE_DB_PASSWORD.
# A function without "secure" gets NO credentials for RDS #2.
FUNCTIONS = {
    "auth": {
        "routes": ["POST /register", "POST /login"],
        "core": "AUTH",
        "secure": "AUTH",
        "memory": 256,  # scrypt needs ~16 MB per hash, plus Python
        "timeout": 15,
    },
    "catalog": {
        "routes": ["GET /categories", "GET /products", "GET /products/{id}"],
        "core": "CATALOG",  # read-only user; no access to RDS #2
        "optional_env": ["IMAGES_BUCKET"],
        "memory": 256,
        "timeout": 10,
    },
    "cart": {
        "routes": [
            "GET /cart",
            "POST /cart/items",
            "PATCH /cart/items/{product_id}",
            "DELETE /cart/items/{product_id}",
        ],
        "core": "CART",  # read-only product checks; cart rows live in DynamoDB
        "optional_env": ["CART_TABLE_NAME"],
        "memory": 256,
        "timeout": 10,
    },
}

# API Gateway throttling: requests per second (rate) and burst, for the whole
# stage and stricter for login to slow down password guessing.
DEFAULT_THROTTLE = {"ThrottlingRateLimit": 20, "ThrottlingBurstLimit": 40}
ROUTE_THROTTLE = {
    "POST /login": {"ThrottlingRateLimit": 2, "ThrottlingBurstLimit": 5},
    "POST /register": {"ThrottlingRateLimit": 2, "ThrottlingBurstLimit": 5},
}


# ---------------------------------------------------------------- config

def load_env(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"Missing {path}. Copy deploy.env.example to deploy.env and fill it in.")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def need(cfg: dict, key: str) -> str:
    value = cfg.get(key, "")
    if not value or value.startswith("CHANGE_ME"):
        sys.exit(f"deploy.env: '{key}' is missing or still a placeholder")
    return value


def function_env(cfg: dict, spec: dict) -> dict:
    jwt_secret = need(cfg, "JWT_SECRET")
    if len(jwt_secret) < 32:
        sys.exit("deploy.env: JWT_SECRET must be at least 32 characters")
    env = {"JWT_SECRET": jwt_secret}
    for db_prefix, key in (("CORE", "core"), ("SECURE", "secure")):
        user_prefix = spec.get(key)
        if not user_prefix:
            continue
        env[f"{db_prefix}_DB_HOST"] = need(cfg, f"{db_prefix}_DB_HOST")
        env[f"{db_prefix}_DB_NAME"] = need(cfg, f"{db_prefix}_DB_NAME")
        env[f"{db_prefix}_DB_USER"] = need(cfg, f"{user_prefix}_{db_prefix}_DB_USER")
        env[f"{db_prefix}_DB_PASSWORD"] = need(cfg, f"{user_prefix}_{db_prefix}_DB_PASSWORD")
    for key in spec.get("optional_env", []):
        if cfg.get(key):
            env[key] = cfg[key]
    return env


# ---------------------------------------------------------------- packaging

def zip_dir(src: Path) -> bytes:
    """Zip a directory with fixed timestamps so identical code gives identical bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(src.rglob("*")):
            if file.is_dir() or "__pycache__" in file.parts:
                continue
            info = zipfile.ZipInfo(file.relative_to(src).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            zf.writestr(info, file.read_bytes(), zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def build_layer() -> bytes:
    out = BUILD / "layer"
    shutil.rmtree(out, ignore_errors=True)
    target = out / "python"
    target.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--quiet",
            "-r", str(ROOT / "layer" / "requirements.txt"),
            "--target", str(target),
            # Download Linux wheels for Lambda, never build from source.
            "--platform", "manylinux2014_x86_64", "--platform", "manylinux_2_28_x86_64",
            "--implementation", "cp",
            "--python-version", RUNTIME.removeprefix("python"), "--only-binary=:all:",
        ],
        check=True,
    )
    shutil.copytree(ROOT / "layer" / "python" / "common", target / "common",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return zip_dir(out)


# ---------------------------------------------------------------- AWS

def publish_layer(lam, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()[:32]
    versions = lam.list_layer_versions(LayerName=LAYER_NAME).get("LayerVersions", [])
    if versions and versions[0].get("Description") == digest:
        print(f"layer   {LAYER_NAME}: unchanged (v{versions[0]['Version']})")
        return versions[0]["LayerVersionArn"]
    result = lam.publish_layer_version(
        LayerName=LAYER_NAME,
        Description=digest,
        Content={"ZipFile": content},
        CompatibleRuntimes=[RUNTIME],
    )
    print(f"layer   {LAYER_NAME}: published v{result['Version']}")
    return result["LayerVersionArn"]


def deploy_function(lam, name: str, spec: dict, *, role_arn: str, layer_arn: str, env: dict, vpc: dict) -> str:
    fn_name = f"{PROJECT}-{name}"
    code = zip_dir(ROOT / "lambdas" / name)
    config = dict(
        Role=role_arn,
        Handler="handler.lambda_handler",
        Runtime=RUNTIME,
        Layers=[layer_arn],
        Environment={"Variables": env},
        VpcConfig=vpc,
        Timeout=spec.get("timeout", 10),
        MemorySize=spec.get("memory", 256),
    )
    try:
        lam.get_function(FunctionName=fn_name)
        exists = True
    except lam.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        lam.update_function_code(FunctionName=fn_name, ZipFile=code)
        lam.get_waiter("function_updated_v2").wait(FunctionName=fn_name)
        result = lam.update_function_configuration(FunctionName=fn_name, **config)
        lam.get_waiter("function_updated_v2").wait(FunctionName=fn_name)
        print(f"lambda  {fn_name}: updated")
    else:
        result = lam.create_function(FunctionName=fn_name, Code={"ZipFile": code}, **config)
        lam.get_waiter("function_active_v2").wait(FunctionName=fn_name)
        print(f"lambda  {fn_name}: created")
    return result["FunctionArn"]


def get_or_create_api(apigw) -> dict:
    for page in apigw.get_paginator("get_apis").paginate():
        for api in page["Items"]:
            if api["Name"] == API_NAME:
                return api
    print(f"api     {API_NAME}: created")
    return apigw.create_api(Name=API_NAME, ProtocolType="HTTP")


def wire_routes(apigw, lam, api: dict, fn_arn: str, routes: list[str], *, region: str, account: str) -> None:
    api_id = api["ApiId"]
    integration_id = next(
        (i["IntegrationId"] for i in apigw.get_integrations(ApiId=api_id)["Items"] if i.get("IntegrationUri") == fn_arn),
        None,
    )
    if integration_id is None:
        integration_id = apigw.create_integration(
            ApiId=api_id,
            IntegrationType="AWS_PROXY",
            IntegrationUri=fn_arn,
            PayloadFormatVersion="2.0",
            TimeoutInMillis=29000,
        )["IntegrationId"]

    target = f"integrations/{integration_id}"
    existing = {r["RouteKey"]: r for r in apigw.get_routes(ApiId=api_id)["Items"]}
    for key in routes:
        if key not in existing:
            apigw.create_route(ApiId=api_id, RouteKey=key, Target=target)
            print(f"route   {key}")
        elif existing[key].get("Target") != target:
            apigw.update_route(ApiId=api_id, RouteId=existing[key]["RouteId"], Target=target)
            print(f"route   {key} (re-pointed)")

    try:
        lam.add_permission(
            FunctionName=fn_arn,
            StatementId=f"apigw-{api_id}",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{region}:{account}:{api_id}/*/*",
        )
    except ClientError as err:
        if err.response["Error"]["Code"] != "ResourceConflictException":
            raise


def ensure_stage(apigw, api: dict) -> None:
    api_id = api["ApiId"]
    route_settings = {k: v for k, v in ROUTE_THROTTLE.items()
                      if k in {r["RouteKey"] for r in apigw.get_routes(ApiId=api_id)["Items"]}}
    stages = {s["StageName"] for s in apigw.get_stages(ApiId=api_id)["Items"]}
    if "$default" not in stages:
        apigw.create_stage(ApiId=api_id, StageName="$default", AutoDeploy=True,
                           DefaultRouteSettings=DEFAULT_THROTTLE, RouteSettings=route_settings)
    else:
        apigw.update_stage(ApiId=api_id, StageName="$default", AutoDeploy=True,
                           DefaultRouteSettings=DEFAULT_THROTTLE, RouteSettings=route_settings)


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=sorted(FUNCTIONS), help="deploy a single function")
    parser.add_argument("--build-only", action="store_true",
                        help="only write the zips to backend/build/ (for uploading by hand in the console)")
    args = parser.parse_args()

    if args.build_only:
        BUILD.mkdir(exist_ok=True)
        layer_zip = BUILD / "layer.zip"
        layer_zip.write_bytes(build_layer())
        print(f"layer   -> {layer_zip}")
        for name in [args.only] if args.only else FUNCTIONS:
            fn_zip = BUILD / f"{name}.zip"
            fn_zip.write_bytes(zip_dir(ROOT / "lambdas" / name))
            print(f"lambda  -> {fn_zip}")
        return

    cfg = load_env(ROOT / "deploy.env")
    region = need(cfg, "AWS_REGION")
    session = boto3.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    role_arn = f"arn:aws:iam::{account}:role/LabRole"
    lam = session.client("lambda")
    apigw = session.client("apigatewayv2")

    vpc = {
        "SubnetIds": [s.strip() for s in need(cfg, "SUBNET_IDS").split(",") if s.strip()],
        "SecurityGroupIds": [need(cfg, "LAMBDA_SECURITY_GROUP_ID")],
    }

    layer_arn = publish_layer(lam, build_layer())
    api = get_or_create_api(apigw)

    names = [args.only] if args.only else list(FUNCTIONS)
    for name in names:
        spec = FUNCTIONS[name]
        fn_arn = deploy_function(lam, name, spec, role_arn=role_arn, layer_arn=layer_arn,
                                 env=function_env(cfg, spec), vpc=vpc)
        wire_routes(apigw, lam, api, fn_arn, spec["routes"], region=region, account=account)

    ensure_stage(apigw, api)
    print(f"\nAPI URL: {api['ApiEndpoint']}")
    print("Put this URL in desktop/.env as API_URL.")


if __name__ == "__main__":
    main()
