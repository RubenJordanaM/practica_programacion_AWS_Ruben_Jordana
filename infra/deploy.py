# infra/deploy.py
import boto3
import json
import os
import time
import logging
import sys
from dotenv import load_dotenv
from package_lambda import package_lambda_function # Importamos nuestro helper

# --- Configuración de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Cargar Variables de Entorno ---
load_dotenv()
try:
    PREFIX = os.environ['UNIQUE_PREFIX']
    REGION = os.environ['AWS_REGION']
    ACCOUNT_ID = os.environ['AWS_ACCOUNT_ID']
    EMAIL = os.environ['NOTIFICATION_EMAIL']
except KeyError as e:
    logger.error(f"Error: La variable de entorno {e} no está definida en el archivo .env")
    sys.exit(1)

# --- Nombres de Recursos ---
# Usamos el prefijo para crear nombres únicos
BUCKET_UPLOADS = f'{PREFIX}-inventory-uploads'
BUCKET_WEB = f'{PREFIX}-inventory-web'
DYNAMO_TABLE = f'{PREFIX}-Inventory'
SNS_TOPIC = f'{PREFIX}-NoStock'
API_NAME = f'{PREFIX}-InventoryAPI'

LAMBDA_ROLE_LOADER = f'{PREFIX}-Lambda-Loader-Role'
LAMBDA_ROLE_API = f'{PREFIX}-Lambda-API-Role'
LAMBDA_ROLE_NOTIFY = f'{PREFIX}-Lambda-Notify-Role'

LAMBDA_FUNC_LOAD = f'{PREFIX}-load_inventory'
LAMBDA_FUNC_API = f'{PREFIX}-get_inventory_api'
LAMBDA_FUNC_NOTIFY = f'{PREFIX}-notify_low_stock'

BUILD_DIR = 'build'
OUTPUTS_FILE = 'deployment-outputs.json'

# --- Inicializar Clientes de Boto3 ---
iam_client = boto3.client('iam', region_name=REGION)
lambda_client = boto3.client('lambda', region_name=REGION)
s3_client = boto3.client('s3', region_name=REGION)
dynamodb_client = boto3.client('dynamodb', region_name=REGION)
sns_client = boto3.client('sns', region_name=REGION)
apigw_client = boto3.client('apigatewayv2', region_name=REGION)
s3_resource = boto3.resource('s3', region_name=REGION)

# --- Política de Confianza (Trust Policy) ---
# Permite que los servicios de AWS (Lambda, API GW) asuman este rol
def get_trust_policy(service_principal):
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": service_principal},
            "Action": "sts:AssumeRole"
        }]
    })

# --- Helper para Esperar (Waiters) ---
def wait(seconds=10):
    logger.info(f"Esperando {seconds}s para que los recursos se propaguen...")
    time.sleep(seconds)

# --- 1. Creación de Roles y Políticas IAM ---
# REEMPLAZO PARA infra/deploy.py

def create_iam_roles():
    logger.info("--- 1. Omitiendo creación de Roles IAM (Usando Rol de Estudiante) ---")

    STUDENT_ROLE_ARN =  "arn:aws:iam::211125670154:role/LabRole"

    if "123456789012" in STUDENT_ROLE_ARN:
        logger.error("¡Error! Debes reemplazar 'STUDENT_ROLE_ARN' con el ARN de tu rol de Lab de estudiante.")
        raise Exception("ARN de rol no configurado en deploy.py")

    logger.info(f"Usando rol preexistente: {STUDENT_ROLE_ARN}")

    # Devolvemos el mismo rol para todas las lambdas
    return {
        'loader': STUDENT_ROLE_ARN,
        'api': STUDENT_ROLE_ARN,
        'notify': STUDENT_ROLE_ARN
    }



# --- 2. Creación de Recursos Base (S3, DDB, SNS) ---
def create_base_resources():
    logger.info("--- 2. Creando Recursos Base (S3, DDB, SNS) ---")
    resources = {}
    
    # --- S3 Bucket de Ingesta (Uploads) ---
    try:
        s3_client.create_bucket(
            Bucket=BUCKET_UPLOADS,
            CreateBucketConfiguration={'LocationConstraint': REGION} if REGION != 'us-east-1' else {}
        )
        logger.info(f"Bucket S3 de ingesta creado: {BUCKET_UPLOADS}")
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        logger.warning(f"Bucket S3 {BUCKET_UPLOADS} ya existe. Reutilizando.")
    except Exception as e:
        logger.error(f"Error creando bucket {BUCKET_UPLOADS}: {e}")
        if "BucketAlreadyExists" in str(e):
             logger.error("El nombre del bucket ya está tomado globalmente. Cambia tu UNIQUE_PREFIX.")
        raise
        
    # --- S3 Bucket para Web (Estático) ---
    try:
        s3_client.create_bucket(
            Bucket=BUCKET_WEB,
            CreateBucketConfiguration={'LocationConstraint': REGION} if REGION != 'us-east-1' else {}
        )
        s3_client.put_public_access_block(
            Bucket=BUCKET_WEB,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicReadGetObject",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{BUCKET_WEB}/*"
                }
            ]
        }
        s3_client.put_bucket_policy(Bucket=BUCKET_WEB, Policy=json.dumps(policy))
        s3_client.put_bucket_website(
            Bucket=BUCKET_WEB,
            WebsiteConfiguration={
                'ErrorDocument': {'Key': 'index.html'},
                'IndexDocument': {'Suffix': 'index.html'},
            }
        )
        web_url = f"http://{BUCKET_WEB}.s3-website.{REGION}.amazonaws.com"
        logger.info(f"Bucket S3 web creado y configurado: {BUCKET_WEB}")
        logger.info(f"URL del Sitio Web: {web_url}")
        resources['web_url'] = web_url
        
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        logger.warning(f"Bucket S3 {BUCKET_WEB} ya existe. Reutilizando.")
        web_url = f"http://{BUCKET_WEB}.s3-website.{REGION}.amazonaws.com"
        resources['web_url'] = web_url
    except Exception as e:
        logger.error(f"Error creando bucket web {BUCKET_WEB}: {e}")
        raise

    # --- Tabla DynamoDB 'Inventory' ---
    try:
        resp = dynamodb_client.create_table(
            TableName=DYNAMO_TABLE,
            AttributeDefinitions=[
                {'AttributeName': 'Store', 'AttributeType': 'S'}, # PK
                {'AttributeName': 'Item', 'AttributeType': 'S'}   # SK
            ],
            KeySchema=[
                {'AttributeName': 'Store', 'KeyType': 'HASH'},
                {'AttributeName': 'Item', 'KeyType': 'RANGE'}
            ],
            BillingMode='PAY_PER_REQUEST',
            StreamSpecification={
                'StreamEnabled': True,
                'StreamViewType': 'NEW_IMAGE' # Enviar la imagen del item *después* del cambio
            }
        )
        logger.info(f"Creando tabla DynamoDB: {DYNAMO_TABLE}. Esperando...")
        waiter = dynamodb_client.get_waiter('table_exists')
        waiter.wait(TableName=DYNAMO_TABLE)
        resources['ddb_arn'] = resp['TableDescription']['TableArn']
        resources['ddb_stream_arn'] = resp['TableDescription']['LatestStreamArn']
        logger.info("Tabla DynamoDB creada y activa.")
    except dynamodb_client.exceptions.ResourceInUseException:
        logger.warning(f"Tabla DynamoDB {DYNAMO_TABLE} ya existe. Reutilizando.")
        resp = dynamodb_client.describe_table(TableName=DYNAMO_TABLE)
        resources['ddb_arn'] = resp['Table']['TableArn']
        resources['ddb_stream_arn'] = resp['Table']['LatestStreamArn']
    except Exception as e:
        logger.error(f"Error creando tabla DynamoDB: {e}")
        raise

    # --- Tópico SNS 'NoStock' ---
    try:
        resp = sns_client.create_topic(Name=SNS_TOPIC)
        resources['sns_topic_arn'] = resp['TopicArn']
        logger.info(f"Tópico SNS creado: {SNS_TOPIC}")
        
        # Suscribir el email
        sns_client.subscribe(
            TopicArn=resources['sns_topic_arn'],
            Protocol='email',
            Endpoint=EMAIL
        )
        logger.info(f"Suscripción enviada a {EMAIL}. Por favor, confirma la suscripción en tu email.")
        
    except Exception as e:
        logger.error(f"Error creando tópico SNS: {e}")
        # Continuar aunque falle, es opcional
    
    return resources

# --- 3. Empaquetar y Desplegar Lambdas ---
def deploy_lambda_functions(roles, resources):
    logger.info("--- 3. Empaquetando y Desplegando Lambdas ---")
    
    # Asegurarse de que el directorio 'build' exista
    if not os.path.exists(BUILD_DIR):
        os.makedirs(BUILD_DIR)
        
    lambda_arns = {}

    # --- Función genérica para empaquetar y crear/actualizar Lambda ---
    def deploy_lambda(func_name, role_arn, handler, source_dir, env_vars={}):
        zip_file = os.path.join(BUILD_DIR, f"{func_name}.zip")
        
        # 1. Empaquetar
        if not package_lambda_function(source_dir, zip_file):
            raise Exception(f"Fallo al empaquetar {source_dir}")
            
        # 2. Leer el .zip
        with open(zip_file, 'rb') as f:
            zip_bytes = f.read()

        # 3. Crear o Actualizar
        try:
            # Intentar crear
            resp = lambda_client.create_function(
                FunctionName=func_name,
                Runtime='python3.11',
                Role=role_arn,
                Handler=handler,
                Code={'ZipFile': zip_bytes},
                Timeout=30,
                MemorySize=128,
                Environment={'Variables': env_vars}
            )
            logger.info(f"Creando función Lambda: {func_name}...")
            # Esperar a que la función esté activa
            waiter = lambda_client.get_waiter('function_active_v2')
            waiter.wait(FunctionName=func_name)
            logger.info(f"Función Lambda {func_name} creada y activa.")
            
        except lambda_client.exceptions.ResourceConflictException:
            # Si ya existe, actualizar el código y la configuración
            logger.warning(f"Función Lambda {func_name} ya existe. Actualizando...")
            resp = lambda_client.update_function_code(
                FunctionName=func_name,
                ZipFile=zip_bytes
            )
            lambda_client.update_function_configuration(
                FunctionName=func_name,
                Role=role_arn,
                Handler=handler,
                Timeout=30,
                Environment={'Variables': env_vars}
            )
            # Esperar a que la actualización termine
            waiter = lambda_client.get_waiter('function_updated_v2')
            waiter.wait(FunctionName=func_name)
            logger.info(f"Función Lambda {func_name} actualizada.")
            
        except Exception as e:
            logger.error(f"Error al desplegar Lambda {func_name}: {e}")
            raise
            
        return lambda_client.get_function(FunctionName=func_name)['Configuration']['FunctionArn']

    # --- Desplegar Lambda A (load_inventory) ---
    lambda_arns['loader'] = deploy_lambda(
        func_name=LAMBDA_FUNC_LOAD,
        role_arn=roles['loader'],
        handler='lambda_function.lambda_handler',
        source_dir='../lambdas/load_inventory',
        env_vars={'DYNAMO_TABLE_NAME': DYNAMO_TABLE}
    )

    # --- Desplegar Lambda B (get_inventory_api) ---
    lambda_arns['api'] = deploy_lambda(
        func_name=LAMBDA_FUNC_API,
        role_arn=roles['api'],
        handler='lambda_function.lambda_handler',
        source_dir='../lambdas/get_inventory_api',
        env_vars={'DYNAMO_TABLE_NAME': DYNAMO_TABLE}
    )

    # --- Desplegar Lambda C (notify_low_stock) ---
    if 'sns_topic_arn' in resources:
        lambda_arns['notify'] = deploy_lambda(
            func_name=LAMBDA_FUNC_NOTIFY,
            role_arn=roles['notify'],
            handler='lambda_function.lambda_handler',
            source_dir='../lambdas/notify_low_stock',
            env_vars={'SNS_TOPIC_ARN': resources['sns_topic_arn']}
        )
    
    return lambda_arns

# --- 4. Configurar Triggers e Integraciones ---
def setup_integrations(lambda_arns, resources):
    logger.info("--- 4. Configurando Triggers e Integraciones ---")
    api_url = None
    
    # --- Trigger S3 -> Lambda A (load_inventory) ---
    try:
        lambda_client.add_permission(
            FunctionName=LAMBDA_FUNC_LOAD,
            StatementId='S3-Invoke-Permission',
            Action='lambda:InvokeFunction',
            Principal='s3.amazonaws.com',
            SourceArn=f'arn:aws:s3:::{BUCKET_UPLOADS}',
            SourceAccount=ACCOUNT_ID
        )
        
        s3_client.put_bucket_notification_configuration(
            Bucket=BUCKET_UPLOADS,
            NotificationConfiguration={
                'LambdaFunctionConfigurations': [
                    {
                        'LambdaFunctionArn': lambda_arns['loader'],
                        'Events': ['s3:ObjectCreated:*'],
                        'Filter': {'Key': {'FilterRules': [
                            {'Name': 'suffix', 'Value': '.csv'}
                        ]}}
                    }
                ]
            }
        )
        logger.info(f"Trigger S3 ({BUCKET_UPLOADS}) -> Lambda ({LAMBDA_FUNC_LOAD}) configurado.")
    except Exception as e:
        logger.error(f"Error configurando trigger S3: {e}")
        # Puede fallar si ya existe, no es crítico para re-ejecuciones

    # --- Trigger DDB Stream -> Lambda C (notify_low_stock) ---
    if 'notify' in lambda_arns:
        try:
            lambda_client.create_event_source_mapping(
                EventSourceArn=resources['ddb_stream_arn'],
                FunctionName=lambda_arns['notify'],
                Enabled=True,
                BatchSize=100,
                StartingPosition='LATEST'
            )
            logger.info(f"Trigger DDB Stream -> Lambda ({LAMBDA_FUNC_NOTIFY}) configurado.")
        except lambda_client.exceptions.ResourceConflictException:
             logger.warning("Event source mapping de DDB Stream ya existe.")
        except Exception as e:
            logger.error(f"Error configurando DDB Stream: {e}")

    # --- API Gateway (HTTP) -> Lambda B (get_inventory_api) ---
    try:
        # 1. Crear la API HTTP
        try:
            resp_api = apigw_client.create_api(
                Name=API_NAME,
                ProtocolType='HTTP',
                CorsConfiguration={
                    'AllowOrigins': ['*'],
                    'AllowMethods': ['GET', 'OPTIONS'],
                    'AllowHeaders': ['Content-Type'],
                }
            )
            api_id = resp_api['ApiId']
            api_url = resp_api['ApiEndpoint']
            logger.info(f"API Gateway (HTTP) creada: {API_NAME} (ID: {api_id})")
        except Exception as e:
            if "ConflictException" in str(e):
                logger.warning(f"API Gateway {API_NAME} ya existe. Buscando...")
                apis = apigw_client.get_apis()['Items']
                api = next((a for a in apis if a['Name'] == API_NAME), None)
                if not api:
                    raise Exception("API Gateway ya existe pero no se pudo encontrar por nombre.")
                api_id = api['ApiId']
                api_url = api['ApiEndpoint']
                logger.info(f"API Gateway encontrada: {API_NAME} (ID: {api_id})")
            else:
                raise
        
        # 2. Crear la Integración
        resp_int = apigw_client.create_integration(
            ApiId=api_id,
            IntegrationType='AWS_PROXY',
            IntegrationUri=lambda_arns['api'],
            PayloadFormatVersion='2.0' # Importante para el formato de 'event'
        )
        integration_id = resp_int['IntegrationId']
        logger.info("Integración de API GW -> Lambda creada.")

        # 3. Crear Rutas (GET /items y GET /items/{store})
        # $default stage ya se crea automáticamente
        
        # Ruta /items
        apigw_client.create_route(
            ApiId=api_id,
            RouteKey='GET /items',
            Target=f'integrations/{integration_id}'
        )
        # Ruta /items/{store}
        apigw_client.create_route(
            ApiId=api_id,
            RouteKey='GET /items/{store}',
            Target=f'integrations/{integration_id}'
        )
        logger.info("Rutas GET /items y GET /items/{store} creadas.")
    # 4. Forzar creación del Stage '$default' (esto faltaba)
        try:
            apigw_client.create_stage(
                ApiId=api_id,
                StageName='$default',
                AutoDeploy=True
            )
            logger.info("Etapa (Stage) '$default' creada con AutoDeploy.")
        except apigw_client.exceptions.ConflictException:
            logger.warning("Etapa (Stage) '$default' ya existe. Reconfigurando AutoDeploy.")
            # Si ya existe, solo nos aseguramos de que tenga AutoDeploy
            apigw_client.update_stage(
                ApiId=api_id,
                StageName='$default',
                AutoDeploy=True
            )
          # 5. Dar permiso a API Gateway para invocar la Lambda B
        lambda_client.add_permission(
            FunctionName=LAMBDA_FUNC_API,
            StatementId='APIGW-Invoke-Permission',
            Action='lambda:InvokeFunction',
            Principal='apigateway.amazonaws.com',
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/*"
        )
        logger.info(f"Permiso otorgado a API Gateway para invocar {LAMBDA_FUNC_API}.")
        logger.info(f"URL de la API: {api_url}")
        
    except Exception as e:
        logger.error(f"Error al crear API Gateway: {e}")
        
    return api_url

# --- 5. Desplegar Sitio Web Estático ---
def deploy_website(web_url, api_url):
    if not api_url:
        logger.error("No se puede desplegar el sitio web: api_url es nulo.")
        return
        
    logger.info("--- 5. Desplegando Sitio Web Estático ---")
    
    # 1. Reemplazar el placeholder en index.html
    try:
        with open('../web/index.html', 'r') as f:
            content = f.read()
            
        content = content.replace('%%API_URL%%', api_url)
        
        # 2. Subir index.html
        s3_resource.Object(BUCKET_WEB, 'index.html').put(
            Body=content,
            ContentType='text/html'
        )
        logger.info(f"Despliegue web completo. Visita: {web_url}")

    except Exception as e:
        logger.error(f"Error al desplegar el sitio web: {e}")

# --- Función Principal (main) ---
def main():
    logger.info(f"--- INICIANDO DESPLIEGUE para {PREFIX} en {REGION} ---")
    
    try:
        # 1. Crear recursos base (necesarios para las políticas IAM)
        resources = create_base_resources()
        
        # 2. Crear roles IAM (ahora que los ARNs de DDB/S3 existen)
        roles = create_iam_roles()
        
        # 3. Empaquetar y desplegar Lambdas
        lambda_arns = deploy_lambda_functions(roles, resources)
        
        # 4. Configurar Triggers y API Gateway
        api_url = setup_integrations(lambda_arns, resources)
        resources['api_url'] = api_url
        
        # 5. Desplegar el frontend
        if api_url:
            deploy_website(resources['web_url'], resources['api_url'])
        else:
            logger.error("No se pudo desplegar el sitio web porque la API Gateway falló.")

        # 6. Guardar salidas
        outputs = {
            'web_url': resources.get('web_url'),
            'api_url': resources.get('api_url'),
            'upload_bucket': BUCKET_UPLOADS,
            'web_bucket': BUCKET_WEB,
            'dynamo_table': DYNAMO_TABLE,
            'sns_topic_arn': resources.get('sns_topic_arn')
        }
        with open(OUTPUTS_FILE, 'w') as f:
            json.dump(outputs, f, indent=2)
            
        logger.info("--- DESPLIEGUE COMPLETADO ---")
        logger.info(f"Sitio Web: {outputs['web_url']}")
        logger.info(f"API Endpoint: {outputs['api_url']}")
        logger.info(f"Sube tus CSVs a: s3://{outputs['upload_bucket']}/")
        logger.info(f"Salidas guardadas en: {OUTPUTS_FILE}")

    except Exception as e:
        logger.error(f"--- ¡FALLÓ EL DESPLIEGUE! ---")
        logger.error(e, exc_info=True)
        logger.error("Revisa el error. Puedes necesitar ejecutar 'teardown.py' antes de re-intentar.")

if __name__ == "__main__":
    # Cambiar al directorio del script para que las rutas relativas (ej: '../lambdas') funcionen
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()